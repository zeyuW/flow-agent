from pathlib import Path
from dataclasses import asdict

from flow_agent.config.settings import settings
from flow_agent.messaging.message_bus import MessageBus
from flow_agent.messaging.event_bus import EventBus
from flow_agent.core.agent_loop import AgentLoop
from flow_agent.core.passive_turn_pipeline import PassiveTurnPipeline
from flow_agent.mcp.client import MCPClient
from flow_agent.mcp.registry import MCPRegistry, MCPServerConfig
from flow_agent.mcp.tool_adapter import MCPToolAdapter
from flow_agent.core.agent import Agent
from flow_agent.core.delegation import DelegationPolicy
from flow_agent.core.context import ConversationContext
from flow_agent.core.orchestrator import Orchestrator
from flow_agent.infra.trace import TraceRecorder
from flow_agent.llm.client import OpenAILLMClient
from flow_agent.llm.assembler import PromptAssembler, PromptBudget
from flow_agent.llm.router import LLMRouter
from flow_agent.behavior.persona import PersonaProfile, PersonaResolver
from flow_agent.memory.organizer import SimpleMemoryOrganizer
from flow_agent.memory.consolidation import MemoryConsolidator
from flow_agent.memory.retriever import KeywordMemoryRetriever
from flow_agent.memory.store import SQLiteMessageStore
from flow_agent.memory.memory_runtime import build_memory_runtime, wire_memory_events
from flow_agent.memory.memory_engine import MemoryEngine
from flow_agent.tools.recall_memory import RecallMemoryTool, RecallMemoryToolAdapter
from flow_agent.tools.memorize import MemorizeTool, MemorizeToolAdapter
from flow_agent.dashboard.store import InMemoryDashboardStore
from flow_agent.dashboard.api import DashboardServer
from flow_agent.background.runtime import BackgroundRuntime, InMemoryJobRegistry
from flow_agent.background.store import InMemoryJobStore
from flow_agent.background.jobs import JobSpec
from flow_agent.background.consolidation_worker import ConsolidationWorker
from flow_agent.infra.paths import DATA_DIR
from flow_agent.infra.persistence import PersistenceManager
from flow_agent.runtime.models import RuntimeHealth, RuntimeUnitSnapshot
from flow_agent.runtime.service import RuntimeService, RuntimeUnit
from flow_agent.subagent.runtime import SubagentRuntime, create_subagent_runtime
from flow_agent.proactive.runtime import ProactiveRuntime
from flow_agent.proactive.runtime import IntervalScheduler
from flow_agent.proactive.sources import (
    LocalFileSource,
    LocalTodoSource,
    MemoryFollowUpSource,
    RSSFeedSource,
    WebSnapshotSource,
)
from flow_agent.proactive.pipeline import (
    CandidateRanker,
    ContentStore,
    DecisionLayer,
    DriftRunner,
    PreGate,
    ProactiveTickRunner,
    SourceGateway,
)
from flow_agent.proactive.judge import ProactiveJudge
from flow_agent.proactive.store import SQLiteProactiveSentStore
from flow_agent.guard.guards import ProactiveFrequencyGuard, ToolGuard
from flow_agent.skills.loader import SkillLoader
from flow_agent.skills.registry import SkillRegistry
from flow_agent.tools.filesystem import ReadFileTool
from flow_agent.tools.registry import ToolRegistry


"""新架构组装：MessageBus + EventBus + AgentLoop + PassiveTurnPipeline

核心流程:
  渠道 → MessageBus.publish_inbound → AgentLoop.consume → PassiveTurnPipeline.process
    → AfterTurn: EventBus.fanout + MessageBus.dispatch_outbound → 渠道
"""


def create_core_components(dashboard: InMemoryDashboardStore | None = None):
    """创建核心组件：Agent, ToolRegistry, LLM 客户端等。

    返回组装好的组件字典，供 create_app_runtime 使用。
    """
    cfg = settings.get()
    PersistenceManager(Path(cfg.storage.memory_db_path)).initialize()

    # 消息存储和上下文
    message_store = SQLiteMessageStore(Path(cfg.storage.memory_db_path))
    context = ConversationContext(store=message_store)

    # 记忆检索器
    retriever = (
        KeywordMemoryRetriever(store=message_store) if cfg.retrieval.enabled else None
    )

    # 记忆整理器
    organizer = (
        SimpleMemoryOrganizer(
            store=message_store,
            max_messages=cfg.memory_policy.max_messages,
            dedupe=cfg.memory_policy.dedupe,
        )
        if cfg.memory_policy.enabled
        else None
    )

    dashboard_store = dashboard or InMemoryDashboardStore()

    # 事件记录器
    recorder = (
        TraceRecorder(path=Path(cfg.observe.trace_path))
        if cfg.observe.enabled
        else None
    )

    # LLM 客户端
    llm_client = OpenAILLMClient(cfg)
    fast_client = (
        OpenAILLMClient(
            cfg,
            model_override=cfg.provider.fast_model,
            api_key_override=cfg.provider.fast_api_key,
            base_url_override=cfg.provider.fast_base_url,
        )
        if cfg.provider.fast_model
        else None
    )
    llm_router = LLMRouter(main_client=llm_client, fast_client=fast_client)

    # 提示词组装器
    prompt_assembler = PromptAssembler(
        PromptBudget(
            max_chars=cfg.prompt_budget.max_chars,
            history_chars=cfg.prompt_budget.history_chars,
            memory_chars=cfg.prompt_budget.memory_chars,
            tool_trace_chars=cfg.prompt_budget.tool_trace_chars,
        )
    )

    # 人设
    persona_resolver = PersonaResolver(
        PersonaProfile(
            name=cfg.persona.name,
            tone_passive=cfg.persona.passive_tone,
            tone_proactive=cfg.persona.proactive_tone,
            default_style=cfg.persona.style,
        )
    )

    # 工具注册表
    tool_registry = ToolRegistry()
    tool_registry.set_guard(
        ToolGuard(
            whitelist={"read_file"}
            | {f"mcp:{s.name}:{t}" for s in (cfg.mcp.servers or []) for t in (s.tools or [])}
            if cfg.tooling.enabled
            else None
        )
    )

    if cfg.tooling.enabled:
        tool_registry.register(ReadFileTool())

    # MCP
    mcp_registry = _build_mcp_registry(cfg)
    _register_mcp_tools(tool_registry, mcp_registry)

    # Agent
    agent = Agent(
        settings=cfg,
        llm_client=llm_client,
        context=context,
        llm_router=llm_router,
        prompt_assembler=prompt_assembler,
        persona_resolver=persona_resolver,
    )

    # Backward-compatible Orchestrator (for proactive and existing code)
    orchestrator = Orchestrator(
        agent=agent,
        tool_registry=tool_registry,
        max_tool_steps=cfg.tooling.max_tool_steps,
        retriever=retriever,
        retrieval_max_items=cfg.retrieval.max_items,
        recorder=recorder,
        organizer=organizer,
        dashboard=dashboard_store,
        tool_selection_max=cfg.tooling.max_tools,
    )

    return {
        "agent": agent,
        "tool_registry": tool_registry,
        "retriever": retriever,
        "organizer": organizer,
        "recorder": recorder,
        "dashboard_store": dashboard_store,
        "orchestrator": orchestrator,
        "message_store": message_store,
    }


def create_message_bus() -> MessageBus:
    """创建消息总线实例。"""
    return MessageBus()


def create_event_bus() -> EventBus:
    """创建事件总线实例。"""
    return EventBus()


def create_passive_turn_pipeline(
    agent: Agent,
    tool_registry: ToolRegistry,
    message_bus: MessageBus,
    event_bus: EventBus,
    retriever=None,
    organizer=None,
    recorder=None,
    dashboard=None,
) -> PassiveTurnPipeline:
    """创建被动回合管道。

    六个阶段：BeforeTurn → BeforeReasoning → PromptRender → Reasoner → AfterReasoning → AfterTurn
    """
    cfg = settings.get()
    return PassiveTurnPipeline(
        agent=agent,
        tool_registry=tool_registry,
        message_bus=message_bus,
        event_bus=event_bus,
        retriever=retriever,
        retrieval_max_items=cfg.retrieval.max_items if cfg.retrieval.enabled else 0,
        max_tool_steps=cfg.tooling.max_tool_steps,
        recorder=recorder,
        organizer=organizer,
        dashboard=dashboard,
        delegation_policy=DelegationPolicy(),
        tool_selection_max=cfg.tooling.max_tools,
    )


def create_agent_loop(
    message_bus: MessageBus,
    pipeline: PassiveTurnPipeline,
) -> AgentLoop:
    """创建 Agent 主循环。"""
    return AgentLoop(
        message_bus=message_bus,
        pipeline=pipeline,
        poll_interval_ms=100,
    )


# 原有 bootstrap 函数保持兼容
def create_orchestrator(dashboard: InMemoryDashboardStore | None = None) -> Orchestrator:
    """创建 Orchestrator（保持向后兼容）。"""
    components = create_core_components(dashboard=dashboard)
    return components["orchestrator"]


def create_app_runtime():
    """组装完整应用运行时。

    返回:
        (orchestrator, proactive_runtime, dashboard_server, background_runtime,
         subagent_runtime, runtime_service, message_bus, event_bus,
         agent_loop, pipeline)
    """
    cfg = settings.get()
    components = create_core_components()
    agent = components["agent"]
    tool_registry = components["tool_registry"]
    retriever = components["retriever"]
    organizer = components["organizer"]
    recorder = components["recorder"]
    dashboard = components["dashboard_store"]
    orchestrator = components["orchestrator"]

    # 创建总线
    message_bus = create_message_bus()
    event_bus = create_event_bus()

    # 创建记忆运行时（双层记忆架构）
    memory_runtime = build_memory_runtime(
        data_dir=Path(DATA_DIR),
        api_key=cfg.api_key,
        base_url=cfg.base_url,
    )
    # 绑定记忆事件（TurnCommitted 后自动触发记忆处理）
    wire_memory_events(memory_runtime, event_bus)

    # 创建管道
    pipeline = create_passive_turn_pipeline(
        agent=agent,
        tool_registry=tool_registry,
        message_bus=message_bus,
        event_bus=event_bus,
        retriever=retriever,
        organizer=organizer,
        recorder=recorder,
        dashboard=dashboard,
    )

    # 创建 Agent 主循环
    agent_loop = create_agent_loop(
        message_bus=message_bus,
        pipeline=pipeline,
    )

    # ── 以下是原有初始化代码（保持向后兼容） ──

    consolidation_worker = (
        ConsolidationWorker(
            memory_store=components["message_store"],
            consolidator=MemoryConsolidator(timeout=60),
        )
        if cfg.background.consolidation_interval_hours is not None
        else None
    )

    background_store = InMemoryJobStore()
    background_registry = InMemoryJobRegistry()
    if consolidation_worker is not None:
        background_registry.register(
            "memory_consolidation",
            JobSpec(
                name="memory_consolidation",
                run_fn=consolidation_worker.run,
                schedule_interval_hours=cfg.background.consolidation_interval_hours,
            ),
        )

    background_runtime = BackgroundRuntime(
        registry=background_registry,
        store=background_store,
        dashboard=dashboard,
    )

    proactive_scheduler = IntervalScheduler()
    proactive_store = SQLiteProactiveSentStore(Path(cfg.storage.memory_db_path))
    proactive_sources = [
        LocalFileSource(name="local_file", root=Path(DATA_DIR)),
        LocalTodoSource(name="local_todo", root=Path(DATA_DIR)),
        MemoryFollowUpSource(
            name="memory_followup",
            store=proactive_store,
            retriever=retriever,
            lookback_days=cfg.proactive.memory_lookback_days,
        ),
        RSSFeedSource(
            name="rss",
            feeds=cfg.proactive.rss_feeds or [],
            store=proactive_store,
        ),
        WebSnapshotSource(
            name="web_snapshot",
            targets=cfg.proactive.web_snapshot_targets or [],
            store=proactive_store,
            frequency_check=ProactiveFrequencyGuard("web_snapshot", interval_hours=cfg.proactive.snapshot_interval_hours),
        ),
    ]
    content_store = ContentStore()
    source_gateway = SourceGateway(sources=proactive_sources, store=content_store)
    candidate_ranker = CandidateRanker()
    decision_layer = DecisionLayer()
    drift_runner = DriftRunner(
        orchestrator=orchestrator,
        tool_registry=tool_registry,
    ) if cfg.proactive.drift_enabled else None
    pre_gate = PreGate()
    judge = ProactiveJudge(
        llm_client=OpenAILLMClient(
            cfg,
            model_override=cfg.proactive.judge_model or cfg.provider.fast_model,
            api_key_override=cfg.provider.fast_api_key,
            base_url_override=cfg.provider.fast_base_url,
        ),
    )
    tick_runner = ProactiveTickRunner(
        scheduler=proactive_scheduler,
        gateway=source_gateway,
        ranker=candidate_ranker,
        layer=decision_layer,
        drift=drift_runner,
        pre_gate=pre_gate,
        judge=judge,
    )
    proactive_runtime = ProactiveRuntime(
        scheduler=proactive_scheduler,
        tick_runner=tick_runner,
    )

    runtime_service = create_runtime_service(
        dashboard=dashboard,
        proactive_runtime=proactive_runtime,
    )

    # 注册记忆工具到工具注册表
    tool_registry.register(
        RecallMemoryToolAdapter(RecallMemoryTool(engine=memory_runtime.engine))
    )
    tool_registry.register(
        MemorizeToolAdapter(
            MemorizeTool(
                memorizer=memory_runtime.memorizer,
                store=memory_runtime.vector_store,
            )
        )
    )

    subagent_runtime = create_subagent_runtime(
        DATA_DIR,
        dashboard=dashboard,
        tasks_file=cfg.subagent.tasks_file,
        max_concurrency=cfg.subagent.max_concurrency,
    )

    dashboard_server = DashboardServer(
        store=dashboard,
        runtime_service=runtime_service,
        host=cfg.channels.dashboard_host,
        port=cfg.channels.dashboard_port,
    )

    return (
        orchestrator,
        proactive_runtime,
        dashboard_server,
        background_runtime,
        subagent_runtime,
        runtime_service,
        message_bus,
        event_bus,
        agent_loop,
        pipeline,
        memory_runtime,
    )


def create_runtime_service(
    dashboard: InMemoryDashboardStore,
    proactive_runtime,
) -> RuntimeService:
    """创建 RuntimeService（保持原有逻辑）。"""

    cfg = settings.get()
    runtime_service = RuntimeService()

    runtime_service.register(
        RuntimeUnit(
            name="turn",
            health_fn=lambda: RuntimeHealth(name="turn", ok=True, detail="orchestrator ready"),
            snapshot_fn=lambda: RuntimeUnitSnapshot(name="turn", running=True, details={}),
        )
    )

    def _proactive_snapshot() -> RuntimeUnitSnapshot:
        status = proactive_runtime.scheduler.status()
        return RuntimeUnitSnapshot(
            name="proactive",
            running=status.running,
            details={
                "is_executing": status.is_executing,
                "last_started_at": (
                    status.last_started_at.isoformat()
                    if status.last_started_at is not None
                    else None
                ),
                "last_finished_at": (
                    status.last_finished_at.isoformat()
                    if status.last_finished_at is not None
                    else None
                ),
            },
        )

    runtime_service.register(
        RuntimeUnit(
            name="proactive",
            start_fn=proactive_runtime.scheduler.start,
            stop_fn=proactive_runtime.scheduler.stop,
            health_fn=lambda: RuntimeHealth(
                name="proactive",
                ok=True,
                detail=f"running={proactive_runtime.scheduler.status().running}",
            ),
            snapshot_fn=_proactive_snapshot,
        )
    )
    runtime_service.register(
        RuntimeUnit(
            name="background",
            health_fn=lambda: RuntimeHealth(name="background", ok=True, detail="ready"),
            snapshot_fn=lambda: RuntimeUnitSnapshot(
                name="background",
                running=True,
                details={"recent_runs": 0},
            ),
        )
    )
    runtime_service.register(
        RuntimeUnit(
            name="subagent",
            health_fn=lambda: RuntimeHealth(name="subagent", ok=True, detail="manager ready"),
            snapshot_fn=lambda: RuntimeUnitSnapshot(
                name="subagent",
                running=True,
                details={"recent_tasks": 0},
            ),
        )
    )
    return runtime_service


def _build_mcp_registry(settings) -> MCPRegistry:
    mcp_registry = MCPRegistry()
    if not settings.mcp.enabled:
        return mcp_registry
    for server in settings.mcp.servers or []:
        handlers = {
            tool_name: (lambda payload, name=tool_name: f"{name}:{payload}")
            for tool_name in server.tools or []
        }
        client = MCPClient(server_name=server.name, tool_handlers=handlers)
        mcp_registry.register_server(
            MCPServerConfig(name=server.name, enabled=server.enabled, tools=server.tools or []),
            client,
        )
        if server.enabled:
            mcp_registry.mount(server.name)
    return mcp_registry


def _register_mcp_tools(tool_registry: ToolRegistry, mcp_registry: MCPRegistry) -> None:
    for server_name, tool_name, description in mcp_registry.discover_tools():
        tool_registry.register(
            MCPToolAdapter(
                server_name=server_name,
                tool_name=tool_name,
                description_text=description,
                registry=mcp_registry,
            )
        )
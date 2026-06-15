from pathlib import Path
from dataclasses import asdict

from flow_agent.config.settings import settings
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

'''
负责组装agent
1、加载配置
2、创建上下文
3、创建llm客户端
4、组装智能体
5、将智能体交给总指挥
'''
# 创建总指挥
def create_orchestrator(dashboard: InMemoryDashboardStore | None = None) -> Orchestrator:
    # 加载配置
    cfg = settings.get()
    PersistenceManager(Path(cfg.storage.memory_db_path)).initialize()
    # 创建消息存储
    message_store = SQLiteMessageStore(Path(cfg.storage.memory_db_path))
    # 创建上下文
    context = ConversationContext(store=message_store)
    # 创建记忆检索器
    retriever = KeywordMemoryRetriever(store=message_store) if cfg.retrieval.enabled else None
    # 创建记忆整理器
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
    # 创建事件记录器
    recorder = (
        TraceRecorder(path=Path(cfg.observe.trace_path))
        if cfg.observe.enabled
        else None
    )
    # 创建LLM客户端
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
    prompt_assembler = PromptAssembler(
        PromptBudget(
            max_chars=cfg.prompt_budget.max_chars,
            history_chars=cfg.prompt_budget.history_chars,
            memory_chars=cfg.prompt_budget.memory_chars,
            tool_trace_chars=cfg.prompt_budget.tool_trace_chars,
        )
    )
    persona_resolver = PersonaResolver(
        PersonaProfile(
            name=cfg.persona.name,
            tone_passive=cfg.persona.passive_tone,
            tone_proactive=cfg.persona.proactive_tone,
            default_style=cfg.persona.style,
        )
    )
    # 创建工具注册表
    tool_registry = ToolRegistry()
    tool_registry.set_guard(
        ToolGuard(
            whitelist={"read_file"} | {f"mcp:{s.name}:{t}" for s in (cfg.mcp.servers or []) for t in (s.tools or [])}
            if cfg.tooling.enabled
            else None
        )
    )
    if cfg.tooling.enabled:
        tool_registry.register(ReadFileTool())
    risk_by_tool = {"read_file": "read-only"}
    for server in (cfg.mcp.servers or []):
        for tool_name in (server.tools or []):
            risk_by_tool[f"mcp:{server.name}:{tool_name}"] = "external-side-effect"
    tool_registry.set_execution_policy(
        ToolRegistry.ToolExecutionPolicy(
            default_max_retries=0,
            max_retries_by_risk={"read-only": 1, "write": 0, "external-side-effect": 0},
            risk_by_tool=risk_by_tool,
        )
    )
    # 创建MCP注册表
    mcp_registry = _build_mcp_registry(cfg)
    # 注册MCP工具
    _register_mcp_tools(tool_registry, mcp_registry)
    # 创建智能体
    agent = Agent(
        settings=cfg,
        llm_client=llm_client,
        llm_router=llm_router,
        prompt_assembler=prompt_assembler,
        persona_resolver=persona_resolver,
        context=context,
    )
    # 创建总指挥
    return Orchestrator(
        agent=agent,
        tool_registry=tool_registry,
        max_tool_steps=cfg.tooling.max_tool_steps,
        retriever=retriever,
        retrieval_max_items=cfg.retrieval.max_items,
        recorder=recorder,
        organizer=organizer,
        dashboard=dashboard_store,
        delegation_policy=DelegationPolicy(
            max_local_chars=cfg.delegation_policy.max_local_chars
        ),
        tool_selection_max=cfg.tooling.tool_selection_max,
    )

# 创建主动运行时
def create_proactive_runtime(dashboard: InMemoryDashboardStore | None = None) -> ProactiveRuntime:
    # 加载配置
    cfg = settings.get()
    PersistenceManager(Path(cfg.storage.memory_db_path)).initialize()
    # 创建消息存储
    db_path = Path(cfg.storage.memory_db_path)
    sent_store = SQLiteProactiveSentStore(db_path=db_path)
    message_store = SQLiteMessageStore(db_path)
    # 创建源
    sources = [
        MemoryFollowUpSource(store=message_store, session_id=cfg.session.default_session_id),
        LocalTodoSource(Path(cfg.proactive.todo_file)),
        LocalFileSource(Path(cfg.proactive.source_file)),
        RSSFeedSource([Path(p) for p in cfg.proactive.rss_feed_files or []]),
        WebSnapshotSource([Path(p) for p in cfg.proactive.web_snapshot_files or []]),
    ]
    gateway = SourceGateway(sources=sources)
    # 创建事件记录器
    recorder = (
        TraceRecorder(path=Path(cfg.observe.trace_path))
        if cfg.observe.enabled
        else None
    )
    # 创建MCP注册表
    mcp_registry = _build_mcp_registry(cfg)
    # 创建技能加载器
    skill_loader = SkillLoader(Path(cfg.proactive.skills_dir))
    # 创建技能注册表
    skill_registry = SkillRegistry(skill_loader.load())
    # 创建工具注册表
    local_tool_registry = ToolRegistry()
    if cfg.tooling.enabled:
        local_tool_registry.register(ReadFileTool())
    # 创建预门的作用:
    # 预门(PreGate)用于在发送主动消息前检测冷却时间，防止发送频率过高。
    # 它会检查距离上一次主动消息已过去的时间是否超过cooldown_seconds，若未超时则跳过本轮发送。
    pre_gate = PreGate(
        sent_store=sent_store,
        cooldown_seconds=cfg.proactive.cooldown_seconds,
    )
    # 创建主动运行时
    tick_runner = ProactiveTickRunner(
        gate=pre_gate,
        gateway=gateway,
        ranker=CandidateRanker(),
        decision_layer=DecisionLayer(
            min_priority_to_send=cfg.proactive.min_priority_to_send
        ),
        judge=ProactiveJudge(),
        drift_runner=DriftRunner(
            Path(cfg.proactive.tasks_file),
            skill_registry=skill_registry,
            available_tools=local_tool_registry.list_tool_names(),
            available_sources={source.name for source in sources},
            available_mcp=set(mcp_registry.mounted_servers()),
        ),
        sent_store=sent_store,
        dedup_ttl_seconds=cfg.proactive.dedup_ttl_seconds,
        content_store=ContentStore(),
        recorder=recorder,
        frequency_guard=ProactiveFrequencyGuard(
            min_interval_seconds=max(0, cfg.proactive.cooldown_seconds // 2)
        ),
    )
    # 创建定时器
    scheduler = IntervalScheduler(
        interval_seconds=cfg.proactive.interval_seconds,
        task=lambda: (tick_runner.tick(), None)[1],
    )
    # 创建主动运行时
    return ProactiveRuntime(
        scheduler=scheduler,
        tick_runner=tick_runner,
    )


def create_dashboard_runtime(
    dashboard: InMemoryDashboardStore,
    runtime_service: RuntimeService | None = None,
    host: str = "127.0.0.1",
    port: int = 8787,
) -> DashboardServer:
    """Create and return a dashboard server (not started)."""

    return DashboardServer(
        host=host,
        port=port,
        store=dashboard,
        runtime_snapshot_provider=(
            (lambda: asdict(runtime_service.snapshot())) if runtime_service is not None else None
        ),
    )


def create_background_runtime(dashboard: InMemoryDashboardStore | None = None) -> BackgroundRuntime:
    """Create a minimal background runtime and register built-in jobs."""

    cfg = settings.get()
    registry = InMemoryJobRegistry()
    store = InMemoryJobStore()
    runtime = BackgroundRuntime(
        registry=registry,
        store=store,
        dashboard=dashboard,
        max_async_queue=cfg.jobs.max_async_queue,
    )

    # stage12: register proactive tick as a managed job (sync execution).
    def proactive_tick_job() -> None:
        create_proactive_runtime().tick_runner.tick()

    registry.register(JobSpec(name="proactive_tick", func=proactive_tick_job, max_retries=0))
    message_store = SQLiteMessageStore(Path(cfg.storage.memory_db_path))
    ConsolidationWorker(
        consolidator=MemoryConsolidator(
            store=message_store,
            max_messages=cfg.memory_policy.max_messages,
            dedupe=cfg.memory_policy.dedupe,
        ),
        session_id=cfg.session.default_session_id,
    ).register(registry)
    return runtime


def create_app_runtime() -> tuple[
    Orchestrator,
    ProactiveRuntime,
    DashboardServer,
    BackgroundRuntime,
    SubagentRuntime,
    RuntimeService,
]:
    """Create a shared runtime across channels/dashboard/background/subagent."""

    dashboard = InMemoryDashboardStore()
    orchestrator = create_orchestrator(dashboard=dashboard)
    proactive_runtime = create_proactive_runtime(dashboard=dashboard)
    cfg = settings.get()
    runtime_service = RuntimeService(dashboard=dashboard)
    dashboard_server = create_dashboard_runtime(
        dashboard=dashboard,
        runtime_service=runtime_service,
        host=cfg.channels.dashboard_host,
        port=cfg.channels.dashboard_port,
    )
    background_runtime = create_background_runtime(dashboard=dashboard)
    subagent_runtime = create_subagent_runtime(
        DATA_DIR,
        dashboard=dashboard,
        tasks_file=cfg.subagent.tasks_file,
        max_concurrency=cfg.subagent.max_concurrency,
    )
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
                details={
                    "recent_runs": len(background_runtime.store.list_runs()),
                },
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
                details={
                    "recent_tasks": len(subagent_runtime.manager.list_recent_tasks(limit=20)),
                },
            ),
        )
    )
    runtime_service.register(
        RuntimeUnit(
            name="dashboard",
            start_fn=dashboard_server.start,
            stop_fn=dashboard_server.stop,
            health_fn=lambda: RuntimeHealth(
                name="dashboard",
                ok=True,
                detail=f"bound={dashboard_server._server is not None}",
            ),
            snapshot_fn=lambda: RuntimeUnitSnapshot(
                name="dashboard",
                running=dashboard_server._server is not None,
                details={
                    "host": cfg.channels.dashboard_host,
                    "port": cfg.channels.dashboard_port,
                },
            ),
        )
    )
    return (
        orchestrator,
        proactive_runtime,
        dashboard_server,
        background_runtime,
        subagent_runtime,
        runtime_service,
    )


# 创建MCP注册表
def _build_mcp_registry(settings) -> MCPRegistry:
    # 创建MCP注册表
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

# 注册MCP工具
def _register_mcp_tools(tool_registry: ToolRegistry, mcp_registry: MCPRegistry) -> None:
    # 注册MCP工具
    for server_name, tool_name, description in mcp_registry.discover_tools():
        # 注册MCP工具
        tool_registry.register(
            MCPToolAdapter(
                server_name=server_name,
                tool_name=tool_name,
                description_text=description,
                registry=mcp_registry,
            )
        )

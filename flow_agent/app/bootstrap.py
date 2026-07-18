from pathlib import Path
from dataclasses import asdict

from flow_agent.config.settings import settings
from flow_agent.messaging.message_bus import MessageBus
from flow_agent.messaging.event_bus import EventBus
from flow_agent.core.agent_loop import AgentLoop
from flow_agent.core.passive_turn_pipeline import PassiveTurnPipeline
from flow_agent.mcp.server_registry import McpServerRegistry
from flow_agent.tools.mcp_manage import McpListTool
from flow_agent.core.agent import Agent
from flow_agent.core.delegation import DelegationPolicy
from flow_agent.core.context import ConversationContext
from flow_agent.infra.trace import TraceRecorder
from flow_agent.llm.client import OpenAILLMClient
from flow_agent.llm.assembler import PromptAssembler, PromptBudget
from flow_agent.llm.router import LLMRouter
from flow_agent.behavior.persona import PersonaProfile, PersonaResolver
from flow_agent.session.session_store import SessionStore
from flow_agent.session.session_manager import SessionManager
from flow_agent.tools.undo import UndoTool
from flow_agent.memory.memory_runtime import build_memory_runtime, wire_memory_events
from flow_agent.memory.memory_engine import MemoryEngine
from flow_agent.memory.maintenance import (
    ConversationConsolidator,
    MemoryOptimizer,
    MemoryOptimizerLoop,
)
from flow_agent.tools.recall_memory import RecallMemoryTool, RecallMemoryToolAdapter
from flow_agent.tools.memorize import MemorizeTool, MemorizeToolAdapter
from flow_agent.background.runtime import BackgroundRuntime, InMemoryJobRegistry
from flow_agent.background.store import InMemoryJobStore
from flow_agent.infra.paths import DATA_DIR, PROJECT_ROOT, WORKSPACE_LAYOUT
from flow_agent.runtime.models import RuntimeHealth, RuntimeUnitSnapshot
from flow_agent.runtime.service import RuntimeService, RuntimeUnit
from flow_agent.runtime.workspace import init_workspace
from flow_agent.subagent.runtime import SubagentRuntime, create_subagent_runtime
from flow_agent.proactive.runtime import build_proactive_runtime
from flow_agent.proactive.mcp_pool import RegistryMcpPool
from flow_agent.guard.guards import ProactiveFrequencyGuard, ToolGuard
from flow_agent.skills.loader import SkillLoader
from flow_agent.skills.registry import SkillRegistry
from flow_agent.tools.filesystem import ReadFileTool
from flow_agent.tools.spawn import SpawnTool
from flow_agent.tools.registry import ToolRegistry
from flow_agent.plugins.plugin_loader import PluginManager
from flow_agent.proactive.sources import LocalFileSource, LocalTaskSource, LocalTodoSource, RSSFeedSource, WebSnapshotSource


"""新架构组装：MessageBus + EventBus + AgentLoop + PassiveTurnPipeline

核心流程:
  渠道 → MessageBus.publish_inbound → AgentLoop.consume → PassiveTurnPipeline.process
    → AfterTurn: EventBus.fanout + MessageBus.dispatch_outbound → 渠道
"""


def create_core_components():
    """创建核心组件：Agent, ToolRegistry, LLM 客户端等。

    返回组装好的组件字典，供 create_app_runtime 使用。
    """
    init_workspace(PROJECT_ROOT)
    cfg = settings.get()

    # 会话上下文
    session_store = SessionStore(Path(cfg.storage.memory_db_path))
    session_manager = SessionManager(session_store)
    context = ConversationContext(session_manager=session_manager)

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
            # 只有已注册的内置、插件或声明式 MCP 工具才能进入执行路径。
            whitelist=None,
        )
    )

    if cfg.tooling.enabled:
        tool_registry.register(ReadFileTool())
        spawn_tool = SpawnTool()
        tool_registry.register(spawn_tool)
        undo_tool = UndoTool()
        undo_tool.session_manager = session_manager
        undo_tool.memory_store = None  # 记忆运行时创建后再注入
        tool_registry.register(undo_tool)

    # MCP
    mcp_registry = _build_mcp_registry(
        cfg,
        WORKSPACE_LAYOUT.mcp_servers_file,
        tool_registry,
    )
    if cfg.tooling.enabled:
        tool_registry.register(McpListTool(mcp_registry))

    # Agent
    agent = Agent(
        settings=cfg,
        llm_client=llm_client,
        context=context,
        llm_router=llm_router,
        prompt_assembler=prompt_assembler,
        persona_resolver=persona_resolver,
    )

    return {
        "agent": agent,
        "tool_registry": tool_registry,
        "recorder": recorder,
        "session_manager": session_manager,
        "llm_client": llm_client,
        "spawn_tool": spawn_tool if cfg.tooling.enabled else None,
        "mcp_registry": mcp_registry,
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
    memory_engine: MemoryEngine | None = None,
    markdown_store=None,
    recorder=None,
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
        memory_engine=memory_engine,
        markdown_store=markdown_store,
        max_tool_steps=cfg.tooling.max_tool_steps,
        recorder=recorder,
        delegation_policy=DelegationPolicy(),
        tool_selection_max=cfg.tooling.tool_selection_max,
        enable_thinking=cfg.model.enable_thinking,
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


def create_app_runtime():
    """组装完整应用运行时。

    返回:
        (proactive_loop, background_runtime, subagent_runtime,
         runtime_service, message_bus, event_bus, agent_loop, pipeline,
         tool_registry, memory_runtime, memory_optimizer_loop,
         mcp_registry, plugin_manager)
    """
    cfg = settings.get()
    
    # MCP 服务器配置
    mcp_servers = []  # 主动数据源仅连接已显式组装的 MCP
    
    components = create_core_components()
    agent = components["agent"]
    tool_registry = components["tool_registry"]
    recorder = components["recorder"]
    session_manager = components["session_manager"]
    llm_client = components["llm_client"]
    spawn_tool = components["spawn_tool"]
    mcp_registry = components["mcp_registry"]

    # 创建总线
    message_bus = create_message_bus()
    event_bus = create_event_bus()

    plugin_manager = PluginManager(
        WORKSPACE_LAYOUT.plugins_dir,
        event_bus=event_bus,
        tool_registry=tool_registry,
        workspace=WORKSPACE_LAYOUT.flow_dir,
        plugin_data_dir=WORKSPACE_LAYOUT.plugin_data_dir,
    )
    import asyncio
    asyncio.run(plugin_manager.load_all())

    if cfg.mcp.enabled:
        try:
            mcp_registry.start(plugin_manager.get_mcp_servers())
        except Exception:
            # 声明或连接失败不应阻止被动对话启动；修复声明后重启即可重试。
            import logging
            logging.getLogger(__name__).exception("MCP 服务代际启动失败")

    # 创建记忆运行时（双层记忆架构）
    memory_runtime = build_memory_runtime(
        data_dir=Path(DATA_DIR),
        memory_dir=WORKSPACE_LAYOUT.memory_dir,
        vector_db_path=WORKSPACE_LAYOUT.memory_vectors_db,
        embedding_cache_path=WORKSPACE_LAYOUT.embedding_cache_file,
        api_key=cfg.embedding.api_key or cfg.api_key,
        base_url=cfg.embedding.base_url or cfg.base_url,
        embedding_model=cfg.embedding.model,
        llm_client=llm_client,
        llm_model=cfg.model.model,
    )
    consolidator = None
    if cfg.memory.enabled:
        consolidator = ConversationConsolidator(
            session_manager=session_manager,
            markdown_store=memory_runtime.markdown_store,
            memorizer=memory_runtime.memorizer,
            llm_client=llm_client,
            min_new_messages=cfg.memory.consolidation_min_new_messages,
            recent_turns_limit=cfg.memory.recent_turns_limit,
        )
    wire_memory_events(memory_runtime, event_bus, consolidator=consolidator)

    memory_optimizer_loop = None
    if cfg.memory.enabled and cfg.memory.optimizer_enabled:
        memory_optimizer_loop = MemoryOptimizerLoop(
            MemoryOptimizer(memory_runtime.markdown_store, llm_client=llm_client),
            interval_seconds=cfg.memory.optimizer_interval_seconds,
        )

    # 创建管道
    pipeline = create_passive_turn_pipeline(
        agent=agent,
        tool_registry=tool_registry,
        message_bus=message_bus,
        event_bus=event_bus,
        memory_engine=memory_runtime.engine,
        markdown_store=memory_runtime.markdown_store,
        recorder=recorder,
    )

    # 创建 Agent 主循环
    agent_loop = create_agent_loop(
        message_bus=message_bus,
        pipeline=pipeline,
    )

    background_store = InMemoryJobStore()
    background_registry = InMemoryJobRegistry()

    background_runtime = BackgroundRuntime(
        registry=background_registry,
        store=background_store,
    )

    # 插件系统暂时禁用，避免异步问题
    proactive_sources = plugin_manager.get_proactive_sources()

    local_sources = [
        LocalFileSource(WORKSPACE_LAYOUT.proactive_source_file),
        LocalTodoSource(WORKSPACE_LAYOUT.proactive_todo_file),
        LocalTaskSource(WORKSPACE_LAYOUT.proactive_tasks_file),
        RSSFeedSource(sorted(WORKSPACE_LAYOUT.rss_sources_dir.glob("*.xml"))),
        WebSnapshotSource(sorted(WORKSPACE_LAYOUT.snapshot_sources_dir.glob("*.txt"))),
    ]
    # 主动链路关闭时不创建资源，也不要求配置目标用户。
    proactive_loop = None
    if cfg.proactive.enabled:
        proactive_channel = "telegram" if cfg.channels.telegram_enabled else "cli"
        proactive_loop = build_proactive_runtime(
            enabled=True,
            chat_id=cfg.proactive.telegram_target_user_id or "",
            llm_client=OpenAILLMClient(
                cfg,
                model_override=cfg.proactive.judge_model or cfg.provider.fast_model,
                api_key_override=cfg.provider.fast_api_key,
                base_url_override=cfg.provider.fast_base_url,
            ),
            memory_engine=memory_runtime.engine,
            markdown_store=memory_runtime.markdown_store,
            session_manager=session_manager,
            outbound_port=message_bus.outbound_port,
            event_bus=event_bus,
            mcp_servers=mcp_servers,
            mcp_pool=RegistryMcpPool(mcp_registry),
            max_per_day=cfg.proactive.max_per_day,
            min_interval=cfg.proactive.min_interval,
            max_interval=cfg.proactive.max_interval,
            cooldown=cfg.proactive.cooldown,
            drift_enabled=cfg.drift.enabled,
            drift_data_dir=cfg.drift.data_dir,
            drift_min_interval_hours=cfg.drift.min_interval_hours,
            drift_max_steps=cfg.drift.max_steps,
            hawkes_enabled=cfg.proactive.hawkes_enabled,
            hawkes_base_intensity=cfg.proactive.hawkes_base_intensity,
            hawkes_excitation_alpha=cfg.proactive.hawkes_excitation_alpha,
            hawkes_decay_beta=cfg.proactive.hawkes_decay_beta,
            hawkes_time_constant=cfg.proactive.hawkes_time_constant,
            proactive_sources=proactive_sources,
            local_sources=local_sources,
            state_path=cfg.proactive.state_path,
            trace_path=cfg.proactive.trace_path,
            channel=proactive_channel,
        )

    runtime_service = create_runtime_service(
        proactive_loop=proactive_loop,
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
                markdown_store=memory_runtime.markdown_store,
            )
        )
    )

    subagent_runtime = create_subagent_runtime(
        DATA_DIR,
        tasks_file=cfg.subagent.tasks_file,
        max_concurrency=cfg.subagent.max_concurrency,
        message_bus=message_bus,
        llm_client=llm_client,
    )

    if spawn_tool is not None:
        spawn_tool._manager = subagent_runtime.manager

    return (
        proactive_loop,
        background_runtime,
        subagent_runtime,
        runtime_service,
        message_bus,
        event_bus,
        agent_loop,
        pipeline,
        tool_registry,
        memory_runtime,
        memory_optimizer_loop,
        mcp_registry,
        plugin_manager,
    )


def create_runtime_service(
    proactive_loop,
) -> RuntimeService:
    """创建 RuntimeService（保持原有逻辑）。"""

    runtime_service = RuntimeService()

    runtime_service.register(
        RuntimeUnit(
            name="turn",
            health_fn=lambda: RuntimeHealth(name="turn", ok=True, detail="agent loop ready"),
            snapshot_fn=lambda: RuntimeUnitSnapshot(name="turn", running=True, details={}),
        )
    )

    def _proactive_health() -> RuntimeHealth:
        if proactive_loop is None:
            return RuntimeHealth(name="proactive", ok=True, detail="disabled")
        snapshot = proactive_loop.status_snapshot()
        return RuntimeHealth(
            name="proactive",
            ok=True,
            detail=(
                f"running={snapshot['running']} "
                f"executing={snapshot['is_executing']}"
            ),
        )

    def _proactive_snapshot() -> RuntimeUnitSnapshot:
        if proactive_loop is None:
            return RuntimeUnitSnapshot(
                name="proactive",
                running=False,
                details={"enabled": False},
                health="stopped",
            )
        details = proactive_loop.status_snapshot()
        return RuntimeUnitSnapshot(
            name="proactive",
            running=bool(details["running"]),
            details=details,
            health="healthy" if details["running"] else "stopped",
        )

    runtime_service.register(
        RuntimeUnit(
            name="proactive",
            stop_fn=(
                proactive_loop.request_stop
                if proactive_loop is not None
                else None
            ),
            health_fn=_proactive_health,
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


def _build_mcp_registry(settings, config_path, tool_registry) -> McpServerRegistry:
    mcp_registry = McpServerRegistry(
        config_path=config_path,
        tool_registry=tool_registry,
        startup_timeout=settings.mcp.startup_timeout_seconds,
        call_timeout=settings.mcp.call_timeout_seconds,
    )
    return mcp_registry

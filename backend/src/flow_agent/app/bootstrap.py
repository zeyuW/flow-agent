from pathlib import Path
from dataclasses import asdict

from infra.config.schema import (
    AppConfig,
    McpConfig,
    ModelEndpointConfig,
    StorageConfig,
    ToolingConfig,
)
from infra.config.watcher import (
    ConfigWatchLoop,
    ConfigWatcher,
    PreparedConfigChange,
)
from flow_agent.messaging.message_bus import MessageBus
from flow_agent.messaging.outbox import SQLiteOutboxStore
from flow_agent.messaging.event_bus import EventBus
from modules.conversation.application.pipeline import PassiveTurnPipeline
from modules.conversation.application.runner import ConversationRunner
from modules.conversation.infra.legacy_message_bus import LegacyMessageBusSource
from modules.delivery.application.ports import DeliveryPort
from modules.delivery.infra.legacy_message_bus import LegacyMessageBusDeliveryPort
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
from flow_agent.background.store import SQLiteJobStore
from flow_agent.background.tools import (
    ListBackgroundJobsTool,
    ListBackgroundRunsTool,
    RunBackgroundJobTool,
)
from flow_agent.scheduler.runtime import SchedulerService
from flow_agent.scheduler.tools import (
    CancelScheduledTaskTool,
    CurrentTimeTool,
    ListScheduledTasksTool,
    ScheduleTaskTool,
)
from flow_agent.infra.paths import DATA_DIR, PROJECT_ROOT, WORKSPACE_LAYOUT
from flow_agent.runtime.models import RuntimeHealth, RuntimeUnitSnapshot
from flow_agent.runtime.service import RuntimeService, RuntimeUnit
from flow_agent.runtime.workspace import init_workspace
from flow_agent.subagent.runtime import SubagentRuntime, create_subagent_runtime
from flow_agent.proactive.runtime import build_proactive_runtime
from flow_agent.proactive.mcp_pool import RegistryMcpPool
from flow_agent.proactive.gate import ProactiveStateStore
from flow_agent.proactive.specs import (
    ProactiveSourceSpecImpl,
    RegisteredProactiveSource,
)
from flow_agent.proactive.tools import (
    ConfigureProactivePolicyTool,
    GetProactiveStatusTool,
)
from flow_agent.guard.guards import ProactiveFrequencyGuard, ToolGuard
from flow_agent.skills.loader import SkillLoader
from flow_agent.skills.registry import SkillRegistry
from flow_agent.tools.filesystem import ReadFileTool
from flow_agent.tools.spawn import SpawnTool
from flow_agent.tools.registry import ToolRegistry
from flow_agent.plugins.plugin_loader import PluginManager
from flow_agent.proactive.sources import (
    LocalFileSource,
    LocalTaskSource,
    LocalTodoSource,
    RSSFeedSource,
    WebSnapshotSource,
)

BACKEND_ROOT = Path(__file__).resolve().parents[3]


"""新架构组装：MessageBus + EventBus + AgentLoop + PassiveTurnPipeline

核心流程:
  渠道 → MessageBus.publish_inbound → AgentLoop.consume → PassiveTurnPipeline.process
    → AfterTurn: EventBus.fanout + MessageBus.dispatch_outbound → 渠道
"""


def create_core_components(config: AppConfig):
    """创建核心组件：Agent, ToolRegistry, LLM 客户端等。

    返回组装好的组件字典，供 create_app_runtime 使用。
    """
    init_workspace(PROJECT_ROOT)
    cfg = config

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
    llm_client = OpenAILLMClient(cfg.llm.main)
    fast_client = OpenAILLMClient(cfg.llm.fast) if cfg.llm.fast else None
    vision_client = OpenAILLMClient(cfg.llm.vision) if cfg.llm.vision else None
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
    spawn_tool: SpawnTool | None = None
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
        cfg.mcp,
        WORKSPACE_LAYOUT.mcp_config_file,
        tool_registry,
    )
    if cfg.tooling.enabled:
        tool_registry.register(McpListTool(mcp_registry))

    # Agent
    agent = Agent(
        system_prompt=cfg.llm.main.system_prompt,
        llm_client=llm_client,
        context=context,
        llm_router=llm_router,
        prompt_assembler=prompt_assembler,
        persona_resolver=persona_resolver,
        vision_client=vision_client,
    )

    return {
        "agent": agent,
        "tool_registry": tool_registry,
        "recorder": recorder,
        "session_manager": session_manager,
        "llm_client": llm_client,
        "spawn_tool": spawn_tool,
        "mcp_registry": mcp_registry,
    }


def create_message_bus(storage: StorageConfig) -> MessageBus:
    """创建消息总线实例。"""
    return MessageBus(
        outbox_store=SQLiteOutboxStore(WORKSPACE_LAYOUT.outbound_messages_db),
        outbox_recovery_window_s=storage.outbox_recovery_window_seconds,
        outbox_recovery_limit=storage.outbox_recovery_limit,
    )


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
    phase_modules_provider=None,
    tool_hook_executor=None,
    *,
    tooling: ToolingConfig,
    enable_thinking: bool,
    delivery_port: DeliveryPort | None = None,
) -> PassiveTurnPipeline:
    """创建被动回合管道。

    六个阶段：BeforeTurn → BeforeReasoning → PromptRender → Reasoner → AfterReasoning → AfterTurn
    """
    return PassiveTurnPipeline(
        agent=agent,
        tool_registry=tool_registry,
        message_bus=message_bus,
        event_bus=event_bus,
        memory_engine=memory_engine,
        markdown_store=markdown_store,
        max_tool_steps=tooling.max_tool_steps,
        recorder=recorder,
        delegation_policy=DelegationPolicy(),
        tool_selection_max=tooling.tool_selection_max,
        enable_thinking=enable_thinking,
        phase_modules_provider=phase_modules_provider,
        tool_hook_executor=tool_hook_executor,
        delivery_port=delivery_port,
    )


def create_agent_loop(
    message_bus: MessageBus,
    pipeline: PassiveTurnPipeline,
) -> ConversationRunner:
    """创建新的对话应用运行器，并隔离迁移期旧实现。"""
    return ConversationRunner(
        source=LegacyMessageBusSource(message_bus),
        processor=pipeline,
        poll_interval_ms=100,
    )


def create_app_runtime(config: AppConfig):
    """组装完整应用运行时。

    返回:
        (proactive_loop, background_runtime, subagent_runtime,
         runtime_service, message_bus, event_bus, agent_loop, pipeline,
         tool_registry, memory_runtime, memory_optimizer_loop,
         mcp_registry, plugin_manager)
    """
    cfg = config

    # MCP 服务器配置
    mcp_servers = []  # 主动数据源仅连接已显式组装的 MCP

    components = create_core_components(cfg)
    agent = components["agent"]
    tool_registry = components["tool_registry"]
    recorder = components["recorder"]
    session_manager = components["session_manager"]
    llm_client = components["llm_client"]
    spawn_tool = components["spawn_tool"]
    mcp_registry = components["mcp_registry"]

    # 创建总线
    message_bus = create_message_bus(cfg.storage)
    event_bus = create_event_bus()
    delivery_port = LegacyMessageBusDeliveryPort(message_bus)

    background_registry = InMemoryJobRegistry()
    background_store = SQLiteJobStore(WORKSPACE_LAYOUT.background_jobs_db)

    plugin_manager = PluginManager(
        WORKSPACE_LAYOUT.plugins_dir,
        event_bus=event_bus,
        tool_registry=tool_registry,
        background_registry=background_registry,
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
    plugin_manager.start_watcher()

    # 创建记忆运行时（双层记忆架构）
    memory_runtime = build_memory_runtime(
        data_dir=Path(DATA_DIR),
        memory_dir=WORKSPACE_LAYOUT.memory_dir,
        vector_db_path=WORKSPACE_LAYOUT.memory_vectors_db,
        embedding_cache_path=WORKSPACE_LAYOUT.embedding_cache_file,
        api_key=cfg.embedding.api_key or cfg.llm.main.api_key,
        base_url=cfg.embedding.base_url or cfg.llm.main.base_url,
        embedding_model=cfg.embedding.model,
        llm_client=llm_client,
        llm_model=cfg.llm.main.model,
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
        phase_modules_provider=plugin_manager.get_phase_modules,
        tool_hook_executor=plugin_manager.tool_hook_executor,
        tooling=cfg.tooling,
        enable_thinking=cfg.llm.main.enable_thinking,
        delivery_port=delivery_port,
    )

    # 创建 Agent 主循环
    agent_loop = create_agent_loop(
        message_bus=message_bus,
        pipeline=pipeline,
    )

    scheduler = SchedulerService(
        store_path=WORKSPACE_LAYOUT.scheduled_tasks_db,
        inbound_queue=message_bus.inbound,
        outbound_port=message_bus.outbound_port,
    )

    background_runtime = BackgroundRuntime(
        registry=background_registry,
        store=background_store,
        scheduler=scheduler,
        event_bus=event_bus,
        max_async_queue=cfg.jobs.max_async_queue,
        max_async_workers=cfg.jobs.max_async_workers,
        shutdown_timeout_seconds=cfg.jobs.timeout_seconds,
        trace_recorder=recorder,
    )
    tool_registry.register_with_meta(
        RunBackgroundJobTool(background_runtime),
        risk="external-side-effect",
    )
    tool_registry.register_with_meta(
        ListBackgroundJobsTool(background_runtime),
        risk="read-only",
    )
    tool_registry.register_with_meta(
        ListBackgroundRunsTool(background_runtime),
        risk="read-only",
    )
    tool_registry.register_with_meta(CurrentTimeTool(), risk="read-only")
    tool_registry.register_with_meta(ScheduleTaskTool(scheduler), risk="write")
    tool_registry.register_with_meta(
        ListScheduledTasksTool(scheduler), risk="read-only"
    )
    tool_registry.register_with_meta(CancelScheduledTaskTool(scheduler), risk="write")

    proactive_state = ProactiveStateStore(cfg.proactive.state_path)
    proactive_target = cfg.proactive.telegram_target_user_id or ""
    if proactive_target:
        proactive_state.set_policy(
            proactive_target,
            enabled=cfg.proactive.idle_enabled,
            idle_threshold_seconds=cfg.proactive.idle_threshold_minutes * 60,
            topics=cfg.proactive.interest_topics,
        )
    if (
        proactive_target
        and proactive_state.get_last_user_interaction(proactive_target) <= 0
    ):
        previous_interaction = proactive_state.get_latest_interaction_event()
        if previous_interaction > 0:
            proactive_state.record_user_interaction(
                proactive_target,
                timestamp=previous_interaction,
            )
    tool_registry.register_with_meta(
        ConfigureProactivePolicyTool(proactive_state),
        risk="write",
    )
    tool_registry.register_with_meta(
        GetProactiveStatusTool(proactive_state),
        risk="read-only",
    )

    # 插件系统暂时禁用，避免异步问题
    proactive_sources = dict(plugin_manager.get_proactive_sources())
    proactive_modules = plugin_manager.get_proactive_modules()
    if cfg.mcp.enabled and "ai-news" in mcp_registry.server_names:
        proactive_sources.setdefault("builtin", []).append(
            RegisteredProactiveSource(
                spec=ProactiveSourceSpecImpl(
                    id="ai-news",
                    channels=("content",),
                    server="ai-news",
                    fetch_tool="get_ai_news",
                ),
                plugin_id="builtin",
            )
        )

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
            chat_id=proactive_target,
            llm_client=OpenAILLMClient(_proactive_model_config(cfg)),
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
            is_busy_fn=lambda: agent_loop.is_processing(proactive_target),
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
            proactive_modules=proactive_modules,
            local_sources=local_sources,
            state_path=cfg.proactive.state_path,
            trace_path=cfg.proactive.trace_path,
            channel=proactive_channel,
            state_store=proactive_state,
        )

    def on_plugin_contributions_changed() -> None:
        """把插件新一代贡献转交给各运行时。"""

        if cfg.mcp.enabled:
            mcp_registry.update_additional_specs(plugin_manager.get_mcp_servers())
        if proactive_loop is not None:
            proactive_loop.request_contributions_refresh(
                [
                    source
                    for sources in plugin_manager.get_proactive_sources().values()
                    for source in sources
                ],
                plugin_manager.get_proactive_modules(),
            )

    plugin_manager.set_contributions_callback(on_plugin_contributions_changed)

    runtime_config_applier = _RuntimeConfigApplier(
        proactive_loop=proactive_loop,
        proactive_target=proactive_target,
        proactive_state=proactive_state,
        pipeline=pipeline,
        background_runtime=background_runtime,
        mcp_registry=mcp_registry,
    )
    background_runtime.config_watcher = ConfigWatchLoop(
        ConfigWatcher(
            BACKEND_ROOT / "config.toml",
            current=cfg,
            appliers=(runtime_config_applier,),
        )
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
            health_fn=lambda: RuntimeHealth(
                name="turn", ok=True, detail="agent loop ready"
            ),
            snapshot_fn=lambda: RuntimeUnitSnapshot(
                name="turn", running=True, details={}
            ),
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
                proactive_loop.request_stop if proactive_loop is not None else None
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
            health_fn=lambda: RuntimeHealth(
                name="subagent", ok=True, detail="manager ready"
            ),
            snapshot_fn=lambda: RuntimeUnitSnapshot(
                name="subagent",
                running=True,
                details={"recent_tasks": 0},
            ),
        )
    )
    return runtime_service


class _RuntimeConfigApplier:
    """把无需重建外部连接的配置变更提交到现有运行时。"""

    def __init__(
        self,
        *,
        proactive_loop,
        proactive_target: str,
        proactive_state,
        pipeline,
        background_runtime,
        mcp_registry,
    ) -> None:
        self.proactive_loop = proactive_loop
        self.proactive_target = proactive_target
        self.proactive_state = proactive_state
        self.pipeline = pipeline
        self.background_runtime = background_runtime
        self.mcp_registry = mcp_registry

    def prepare(
        self,
        current: AppConfig,
        candidate: AppConfig,
    ) -> PreparedConfigChange:
        """校验热更新边界，并生成仅含已验证赋值的提交动作。"""

        if candidate != _reloadable_projection(current, candidate):
            raise ValueError("当前配置变更需要重启服务后生效")

        import logging

        level = candidate.logging.level.upper()
        valid_levels = {
            "CRITICAL",
            "FATAL",
            "ERROR",
            "WARN",
            "WARNING",
            "INFO",
            "DEBUG",
            "NOTSET",
        }
        if level not in valid_levels:
            raise ValueError(f"无效日志级别: {candidate.logging.level}")

        if self.proactive_loop is not None:
            from flow_agent.proactive.proactive_loop import HawkesConfig

            HawkesConfig(
                base_intensity=candidate.proactive.hawkes_base_intensity,
                excitation_alpha=candidate.proactive.hawkes_excitation_alpha,
                decay_beta=candidate.proactive.hawkes_decay_beta,
                time_constant=candidate.proactive.hawkes_time_constant,
                min_interval=candidate.proactive.min_interval,
                max_interval=candidate.proactive.max_interval,
            )

        def commit() -> None:
            if self.proactive_target:
                self.proactive_state.set_policy(
                    self.proactive_target,
                    enabled=candidate.proactive.idle_enabled,
                    idle_threshold_seconds=(
                        candidate.proactive.idle_threshold_minutes * 60
                    ),
                    topics=candidate.proactive.interest_topics,
                )
            if self.proactive_loop is not None:
                self.proactive_loop.apply_runtime_config(
                    min_interval=candidate.proactive.min_interval,
                    max_interval=candidate.proactive.max_interval,
                    max_per_day=candidate.proactive.max_per_day,
                    cooldown=candidate.proactive.cooldown,
                    base_intensity=candidate.proactive.hawkes_base_intensity,
                    excitation_alpha=candidate.proactive.hawkes_excitation_alpha,
                    decay_beta=candidate.proactive.hawkes_decay_beta,
                    time_constant=candidate.proactive.hawkes_time_constant,
                    drift_min_interval_hours=candidate.drift.min_interval_hours,
                )
            logging.getLogger().setLevel(level)
            self.pipeline.max_tool_steps = candidate.tooling.max_tool_steps
            self.pipeline.tool_selection_max = candidate.tooling.tool_selection_max
            self.background_runtime.shutdown_timeout_seconds = (
                candidate.jobs.timeout_seconds
            )
            self.mcp_registry.startup_timeout = candidate.mcp.startup_timeout_seconds
            self.mcp_registry.call_timeout = candidate.mcp.call_timeout_seconds

        return PreparedConfigChange(commit=commit, discard=lambda: None)


def _reloadable_projection(
    current: AppConfig,
    candidate: AppConfig,
) -> AppConfig:
    """把候选中的可热更新字段投影到当前快照。"""

    return current.model_copy(
        update={
            "logging": candidate.logging,
            "tooling": current.tooling.model_copy(
                update={
                    "max_tool_steps": candidate.tooling.max_tool_steps,
                    "tool_selection_max": candidate.tooling.tool_selection_max,
                }
            ),
            "mcp": current.mcp.model_copy(
                update={
                    "startup_timeout_seconds": candidate.mcp.startup_timeout_seconds,
                    "call_timeout_seconds": candidate.mcp.call_timeout_seconds,
                }
            ),
            "jobs": current.jobs.model_copy(
                update={"timeout_seconds": candidate.jobs.timeout_seconds}
            ),
            "proactive": current.proactive.model_copy(
                update={
                    "max_per_day": candidate.proactive.max_per_day,
                    "min_interval": candidate.proactive.min_interval,
                    "max_interval": candidate.proactive.max_interval,
                    "cooldown": candidate.proactive.cooldown,
                    "hawkes_base_intensity": (
                        candidate.proactive.hawkes_base_intensity
                    ),
                    "hawkes_excitation_alpha": (
                        candidate.proactive.hawkes_excitation_alpha
                    ),
                    "hawkes_decay_beta": candidate.proactive.hawkes_decay_beta,
                    "hawkes_time_constant": (candidate.proactive.hawkes_time_constant),
                    "idle_enabled": candidate.proactive.idle_enabled,
                    "idle_threshold_minutes": (
                        candidate.proactive.idle_threshold_minutes
                    ),
                    "interest_topics": candidate.proactive.interest_topics,
                }
            ),
            "drift": current.drift.model_copy(
                update={
                    "min_interval_hours": candidate.drift.min_interval_hours,
                }
            ),
        }
    )


def _build_mcp_registry(
    config: McpConfig,
    config_path,
    tool_registry,
) -> McpServerRegistry:
    mcp_registry = McpServerRegistry(
        config_path=config_path,
        tool_registry=tool_registry,
        startup_timeout=config.startup_timeout_seconds,
        call_timeout=config.call_timeout_seconds,
    )
    return mcp_registry


def _proactive_model_config(config: AppConfig) -> ModelEndpointConfig:
    endpoint = config.llm.fast or config.llm.main
    if not config.proactive.judge_model:
        return endpoint
    return ModelEndpointConfig(
        model=config.proactive.judge_model,
        api_key=endpoint.api_key,
        base_url=endpoint.base_url,
    )

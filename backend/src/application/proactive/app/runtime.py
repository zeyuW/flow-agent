"""主动链路运行时组装入口。"""

from collections.abc import Mapping
from pathlib import Path
from infra.telemetry.trace import TraceRecorder

from application.proactive.infra.data_gateway import DataGateway
from application.proactive.app.drift_pipeline import DriftTurnPipeline
from application.proactive.infra.drift_store import DriftStateStore
from application.proactive.app.events import ProactiveEventBridge
from application.proactive.infra.gate import AnyActionGate, ProactiveStateStore
from application.proactive.app.judge_loop import JudgeLoop
from application.proactive.app.lifecycle import compile_proactive_lifecycle
from application.proactive.app.mcp_polling import McpPollingModule
from application.proactive.infra.mcp_pool import McpClientPool
from application.proactive.app.loop import HawkesConfig, ProactiveLoop
from application.proactive.app.pipeline import ProactiveTurnPipeline
from application.ports.message_sender import MessageSender


def _flatten_sources(proactive_sources) -> list:
    """兼容按插件分组和已扁平化的主动数据源输入。"""

    if not proactive_sources:
        return []
    if isinstance(proactive_sources, Mapping):
        flattened = []
        for sources in proactive_sources.values():
            flattened.extend(sources)
        return flattened
    return list(proactive_sources)


def build_proactive_runtime(
    *,
    enabled: bool = True,
    chat_id: str = "",
    llm_client=None,
    memory_engine=None,
    markdown_store=None,
    session_manager=None,
    message_sender: MessageSender | None = None,
    outbound_port=None,
    event_bus=None,
    mcp_servers: list[dict] | None = None,
    mcp_pool=None,
    max_per_day: int = 5,
    min_interval: float = 60.0,
    max_interval: float = 1800.0,
    is_busy_fn=None,
    cooldown: float = 120.0,
    drift_enabled: bool = False,
    drift_data_dir: str = "",
    drift_min_interval_hours: float = 1.0,
    drift_max_steps: int = 10,
    hawkes_enabled: bool = True,
    hawkes_base_intensity: float = 0.1,
    hawkes_excitation_alpha: float = 0.5,
    hawkes_decay_beta: float = 0.1,
    hawkes_time_constant: float = 60.0,
    proactive_sources=None,
    proactive_modules: list[object] | None = None,
    local_source_file: str | Path | None = None,
    state_path=None,
    trace_path=None,
    local_sources=None,
    channel: str = "cli",
    state_store: ProactiveStateStore | None = None,
) -> ProactiveLoop | None:
    """组装主动链路，并在启用时接入用户回合事件。"""

    if not enabled:
        return None

    pool = mcp_pool or McpClientPool()
    for server in mcp_servers or []:
        if hasattr(pool, "add_server"):
            pool.add_server(**server)

    sources = _flatten_sources(proactive_sources)
    lifecycle = compile_proactive_lifecycle(
        proactive_modules or [],
        initial_slots=("proactive:tick",),
    )
    local_path = Path(local_source_file) if local_source_file else None
    gateway = DataGateway(
        pool,
        sources,
        local_source_file=local_path,
        local_sources=local_sources,
    )
    state = state_store or ProactiveStateStore(state_path)
    judge = JudgeLoop(
        llm_client=llm_client,
        memory_engine=memory_engine,
        markdown_store=markdown_store,
    )
    trace_recorder = TraceRecorder(Path(trace_path)) if trace_path else None
    any_action = AnyActionGate(
        max_per_day=max_per_day,
        min_interval=cooldown,
    )

    drift_pipeline = None
    if drift_enabled and drift_data_dir:
        drift_store = DriftStateStore(drift_data_dir)
        drift_pipeline = DriftTurnPipeline(
            state_store=drift_store,
            llm_client=llm_client,
            memory_engine=memory_engine,
            mcp_pool=pool,
            max_steps=drift_max_steps,
            workspace=drift_data_dir,
        )

    pipeline = ProactiveTurnPipeline(
        state_store=state,
        gateway=gateway,
        judge=judge,
        any_action=any_action,
        cooldown=cooldown,
        session_manager=session_manager,
        message_sender=message_sender,
        outbound_port=outbound_port,
        drift_pipeline=drift_pipeline,
        drift_enabled=drift_enabled,
        drift_min_interval_hours=drift_min_interval_hours,
        mcp_pool=pool,
        proactive_sources=sources,
        channel=channel,
        lifecycle=lifecycle,
    )

    polling_module = McpPollingModule(pool, sources) if sources else None
    hawkes_config = HawkesConfig(
        base_intensity=hawkes_base_intensity,
        excitation_alpha=hawkes_excitation_alpha,
        decay_beta=hawkes_decay_beta,
        time_constant=hawkes_time_constant,
        min_interval=min_interval,
        max_interval=max_interval,
    )
    loop = ProactiveLoop(
        pipeline=pipeline,
        mcp_pool=pool,
        chat_id=chat_id,
        min_interval=min_interval,
        max_interval=max_interval,
        is_busy_fn=is_busy_fn,
        hawkes_config=hawkes_config,
        hawkes_enabled=hawkes_enabled,
        polling_module=polling_module,
        state_store=state,
        trace_recorder=trace_recorder,
    )

    if event_bus is not None:
        bridge = ProactiveEventBridge(
            loop=loop,
            target_session_id=chat_id,
            target_channel=channel,
        )
        event_bus.subscribe(bridge)
        loop._event_bridge = bridge

    return loop

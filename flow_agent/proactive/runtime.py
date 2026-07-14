"""主动运行时工厂：使用霍克斯过程构建 build_proactive_runtime。"""

from pathlib import Path

from flow_agent.proactive.data_gateway import DataGateway
from flow_agent.proactive.drift_store import DriftStateStore
from flow_agent.proactive.drift_pipeline import DriftTurnPipeline
from flow_agent.proactive.gate import AnyActionGate, ProactiveStateStore
from flow_agent.proactive.judge_loop import JudgeLoop
from flow_agent.proactive.mcp_pool import McpClientPool
from flow_agent.proactive.mcp_polling import McpPollingModule
from flow_agent.proactive.proactive_loop import HawkesConfig, ProactiveLoop
from flow_agent.proactive.proactive_pipeline import ProactiveTurnPipeline
from flow_agent.infra.paths import DATA_DIR


def build_proactive_runtime(
    *,
    chat_id: str = "",
    llm_client=None,
    memory_engine=None,
    session_manager=None,
    outbound_port=None,
    mcp_servers: list[dict] | None = None,
    max_per_day: int = 5,
    min_interval: float = 60.0,
    max_interval: float = 1800.0,
    is_busy_fn=None,
    cooldown: float = 120.0,
    drift_enabled: bool = False,
    drift_data_dir: str = "",
    drift_min_interval_hours: float = 1.0,
    drift_max_steps: int = 10,
    # 霍克斯过程配置
    hawkes_enabled: bool = True,
    hawkes_base_intensity: float = 0.1,
    hawkes_excitation_alpha: float = 0.5,
    hawkes_decay_beta: float = 0.1,
    hawkes_time_constant: float = 60.0,
    # 插件系统集成
    proactive_sources: list = None,
    # 通道配置
    channel: str = "cli",
) -> ProactiveLoop:
    """构建完整主动链路运行时，支持霍克斯过程模型和插件系统。

    返回的 ProactiveLoop 可作为后台任务启动。
    """
    pool = McpClientPool()
    if mcp_servers:
        for s in mcp_servers:
            pool.add_server(**s)

    state = ProactiveStateStore()
    
    # 扁平化所有插件的数据源
    all_proactive_sources = []
    if proactive_sources:
        for sources_list in proactive_sources.values():
            all_proactive_sources.extend(sources_list)
    
    gateway = DataGateway(pool, all_proactive_sources, local_source_file=Path(DATA_DIR) / "proactive" / "test_feed.txt")
    judge = JudgeLoop(llm_client=llm_client, memory_engine=memory_engine)
    # 简化的 Gate：仅保留每日最大次数限制，调度完全由霍克斯过程控制
    any_action = AnyActionGate(max_per_day=max_per_day)

    # 漂移管道
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
        outbound_port=outbound_port,
        drift_pipeline=drift_pipeline,
        drift_enabled=drift_enabled,
        drift_min_interval_hours=drift_min_interval_hours,
        mcp_pool=pool,
        proactive_sources=all_proactive_sources,
        channel=channel,
    )

    # 霍克斯过程配置
    hawkes_config = None
    if hawkes_enabled:
        hawkes_config = HawkesConfig(
            base_intensity=hawkes_base_intensity,
            excitation_alpha=hawkes_excitation_alpha,
            decay_beta=hawkes_decay_beta,
            time_constant=hawkes_time_constant,
            min_interval=min_interval,
            max_interval=max_interval,
        )

    # MCP 轮询模块（如果有插件声明了数据源）
    polling_module = None
    all_proactive_sources = []  # 扁平化的 RegisteredProactiveSource 列表
    if proactive_sources:
        from flow_agent.proactive.specs import RegisteredProactiveSource
        # 扁平化所有插件的数据源
        for sources_list in proactive_sources.values():
            all_proactive_sources.extend(sources_list)
        if all_proactive_sources:
            polling_module = McpPollingModule(pool, all_proactive_sources)

    loop = ProactiveLoop(
        pipeline=pipeline,
        mcp_pool=pool,
        chat_id=chat_id,
        min_interval=min_interval,
        max_interval=max_interval,
        is_busy_fn=is_busy_fn,
        hawkes_config=hawkes_config,
        polling_module=polling_module,
    )

    return loop

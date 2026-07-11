"""Proactive runtime factory: build_proactive_runtime with Hawkes process (spec proactive)。"""

from flow_agent.proactive.data_gateway import DataGateway
from flow_agent.proactive.drift_store import DriftStateStore
from flow_agent.proactive.drift_pipeline import DriftTurnPipeline
from flow_agent.proactive.gate import AnyActionGate, ProactiveStateStore
from flow_agent.proactive.judge_loop import JudgeLoop
from flow_agent.proactive.mcp_pool import McpClientPool
from flow_agent.proactive.proactive_loop import HawkesConfig, ProactiveLoop
from flow_agent.proactive.proactive_pipeline import ProactiveTurnPipeline


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
) -> ProactiveLoop:
    """构建完整主动链路运行时，支持霍克斯过程模型 (spec proactive)。

    返回的 ProactiveLoop 可作为后台任务启动。
    """
    pool = McpClientPool()
    if mcp_servers:
        for s in mcp_servers:
            pool.add_server(**s)

    state = ProactiveStateStore()
    gateway = DataGateway(pool)
    judge = JudgeLoop(llm_client=llm_client, memory_engine=memory_engine)
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

    loop = ProactiveLoop(
        pipeline=pipeline,
        mcp_pool=pool,
        chat_id=chat_id,
        min_interval=min_interval,
        max_interval=max_interval,
        is_busy_fn=is_busy_fn,
        hawkes_config=hawkes_config,
    )

    return loop

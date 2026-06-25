"""Proactive runtime factory: build_proactive_runtime (spec 1a)."""

from flow_agent.proactive.data_gateway import DataGateway
from flow_agent.proactive.drift_store import DriftStateStore
from flow_agent.proactive.drift_pipeline import DriftTurnPipeline
from flow_agent.proactive.gate import AnyActionGate, ProactiveStateStore
from flow_agent.proactive.judge_loop import JudgeLoop
from flow_agent.proactive.mcp_pool import McpClientPool
from flow_agent.proactive.proactive_loop import ProactiveLoop
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
    min_interval: float = 30.0,
    max_interval: float = 300.0,
    is_busy_fn=None,
    cooldown: float = 120.0,
    drift_enabled: bool = False,
    drift_data_dir: str = "",
    drift_min_interval_hours: float = 1.0,
    drift_max_steps: int = 10,
) -> ProactiveLoop:
    """构建完整主动链路运行时 (spec 1a)。

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

    loop = ProactiveLoop(
        pipeline=pipeline,
        mcp_pool=pool,
        chat_id=chat_id,
        min_interval=min_interval,
        max_interval=max_interval,
        is_busy_fn=is_busy_fn,
    )

    return loop

"""Proactive runtime factory: build_proactive_runtime (spec 1a)."""

from flow_agent.proactive.data_gateway import DataGateway
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
        is_busy_fn = None
    cooldown: float = 120.0,
) -> ProactiveLoop:
    """Build the full proactive runtime (spec 1a).

    Returns a ProactiveLoop that can be started as a background task.
    """
    pool = McpClientPool()
    if mcp_servers:
        for s in mcp_servers:
            pool.add_server(**s)

    state = ProactiveStateStore()
    gateway = DataGateway(pool)
    judge = JudgeLoop(llm_client=llm_client, memory_engine=memory_engine)
    any_action = AnyActionGate(max_per_day=max_per_day)

    pipeline = ProactiveTurnPipeline(
        state_store=state,
        gateway=gateway,
        judge=judge,
        any_action=any_action,
        cooldown=cooldown,
        session_manager=session_manager,
        outbound_port=outbound_port,
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

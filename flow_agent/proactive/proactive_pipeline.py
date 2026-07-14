"""ProactiveTurnPipeline: 五阶段管道 + 漂移回退。"""

import logging
import time

from flow_agent.proactive.data_gateway import DataGateway
from flow_agent.proactive.deliver import deliver_message
from flow_agent.proactive.gate import AnyActionGate, ProactiveStateStore, check_gate
from flow_agent.proactive.judge_loop import JudgeLoop
from flow_agent.proactive.models import AgentTick
from flow_agent.proactive.resolve import resolve_decision

logger = logging.getLogger(__name__)


class ProactiveTurnPipeline:
    """单次主动 tick 的五阶段管道 + 漂移回退。"""

    def __init__(
        self,
        *,
        state_store: ProactiveStateStore,
        gateway: DataGateway,
        judge: JudgeLoop,
        any_action: AnyActionGate,
        cooldown: float = 120.0,
        session_manager=None,
        outbound_port=None,
        drift_pipeline=None,
        drift_enabled: bool = False,
        drift_min_interval_hours: float = 1.0,
        mcp_pool=None,
        proactive_sources: list = None,
        channel: str = "cli",
    ) -> None:
        self._state = state_store
        self._gateway = gateway
        self._judge = judge
        self._any_action = any_action
        self._cooldown = cooldown
        self._session_manager = session_manager
        self._outbound_port = outbound_port
        self._drift = drift_pipeline
        self._drift_enabled = drift_enabled
        self._drift_min_interval = drift_min_interval_hours * 3600
        self._mcp_pool = mcp_pool
        self._proactive_sources = proactive_sources or []
        self._channel = channel
        logger.info(f"ProactiveTurnPipeline initialized with channel={channel}")

    async def run(self, *, chat_id: str = "", base_score: float = 0.0, is_busy: bool = False) -> AgentTick:
        """执行一次完整 tick：Gate → Fetch → Judge → Resolve → Deliver，无数据时尝试漂移。"""
        tick = AgentTick(chat_id=chat_id, base_score=base_score)

        # 阶段 1: Gate
        tick.gate_result = check_gate(
            chat_id=chat_id,
            is_busy=is_busy,
            state_store=self._state,
            any_action=self._any_action,
            cooldown=self._cooldown,
            base_score=base_score,
        )
        if not tick.gate_result.passed:
            logger.debug("gate blocked: %s", tick.gate_result.reason)
            return tick

        # 阶段 2: Fetch
        tick.gateway_result = await self._gateway.run()

        # ── 漂移回退：无数据时尝试漂移 ──
        if self._should_enter_drift(tick.gateway_result):
            drift_tick = await self._drift.run(connected_mcp=set())
            tick.drift_tick = drift_tick
            # 标记 drift 运行时间
            self._state.mark_drift_run()
            logger.info("drift executed: runs=%d msg=%s", len(drift_tick.runs), bool(drift_tick.message))
            # 如果 drift 产生了消息，走发送链路
            if drift_tick.message:
                from flow_agent.proactive.models import JudgeResult
                tick.judge_result = JudgeResult(decision="reply", message=drift_tick.message)
                tick.resolve_result = resolve_decision(tick.judge_result, state_store=self._state, chat_id=chat_id)
                if tick.resolve_result.decision == "send":
                    tick.deliver_result = await deliver_message(
                        tick.resolve_result,
                        chat_id=chat_id,
                        session_manager=self._session_manager,
                        outbound_port=self._outbound_port,
                    )
            return tick

        # 阶段 3: Judge
        tick.judge_result = await self._judge.evaluate(tick.gateway_result, chat_id)

        # 阶段 4: Resolve
        tick.resolve_result = resolve_decision(
            tick.judge_result,
            state_store=self._state,
            chat_id=chat_id,
            mcp_pool=self._mcp_pool,
            sources=self._proactive_sources,
        )

        # 阶段 5: Deliver
        if tick.resolve_result.decision == "send":
            tick.deliver_result = await deliver_message(
                tick.resolve_result,
                chat_id=chat_id,
                session_manager=self._session_manager,
                outbound_port=self._outbound_port,
                channel=self._channel if hasattr(self, '_channel') else "cli",
            )

        return tick

    def _should_enter_drift(self, gateway_result) -> bool:
        # 无 alert 且无 content
        if not self._drift or not self._drift_enabled:
            return False
        if gateway_result.alerts or gateway_result.content:
            return False

        # 检查最小间隔
        last = self._state.get_drift_last_at()
        if last > 0 and (time.time() - last) < self._drift_min_interval:
            return False

        return True

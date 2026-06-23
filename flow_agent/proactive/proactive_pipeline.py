"""ProactiveTurnPipeline: 5-stage pipeline (Gate → Fetch → Judge → Resolve → Deliver) (spec 1e, 2-6)."""

import asyncio
import logging

from flow_agent.proactive.data_gateway import DataGateway
from flow_agent.proactive.deliver import deliver_message
from flow_agent.proactive.gate import AnyActionGate, ProactiveStateStore, check_gate
from flow_agent.proactive.judge_loop import JudgeLoop
from flow_agent.proactive.models import AgentTick
from flow_agent.proactive.resolve import resolve_decision

logger = logging.getLogger(__name__)


class ProactiveTurnPipeline:
    """Orchestrates a single proactive tick through 5 stages (spec 2a)."""

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
    ) -> None:
        self._state = state_store
        self._gateway = gateway
        self._judge = judge
        self._any_action = any_action
        self._cooldown = cooldown
        self._session_manager = session_manager
        self._outbound_port = outbound_port

    async def run(self, *, chat_id: str = "", base_score: float = 0.0, is_busy: bool = False) -> AgentTick:
        """Execute one full tick: Gate → Fetch → Judge → Resolve → Deliver (spec 1e)."""
        tick = AgentTick(chat_id=chat_id, base_score=base_score)

        # Stage 1: Gate (spec 2)
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

        # Stage 2: Fetch (spec 3)
        tick.gateway_result = await self._gateway.run()

        # Stage 3: Judge (spec 4)
        tick.judge_result = await self._judge.evaluate(tick.gateway_result, chat_id)

        # Stage 4: Resolve (spec 5)
        tick.resolve_result = resolve_decision(
            tick.judge_result,
            state_store=self._state,
            chat_id=chat_id,
        )

        # Stage 5: Deliver (spec 6)
        if tick.resolve_result.decision == "send":
            tick.deliver_result = await deliver_message(
                tick.resolve_result,
                chat_id=chat_id,
                session_manager=self._session_manager,
                outbound_port=self._outbound_port,
            )

        return tick

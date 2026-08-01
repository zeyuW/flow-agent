"""主动检查的五阶段管道和漂移回退。"""

import logging
import time

from flow_agent.proactive.data_gateway import DataGateway
from flow_agent.proactive.deliver import deliver_message
from flow_agent.proactive.gate import AnyActionGate, ProactiveStateStore, check_gate
from flow_agent.proactive.judge_loop import JudgeLoop
from flow_agent.proactive.lifecycle import ProactiveLifecycle, ProactiveModuleContext
from flow_agent.proactive.models import AgentTick, JudgeResult
from flow_agent.proactive.resolve import resolve_decision

logger = logging.getLogger(__name__)


class ProactiveTurnPipeline:
    """按准入、采集、评估、解析、投递顺序执行单次主动检查。"""

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
        proactive_sources: list | None = None,
        channel: str = "cli",
        lifecycle: ProactiveLifecycle | None = None,
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
        self._drift_min_interval = drift_min_interval_hours * 3600.0
        self._mcp_pool = mcp_pool
        self._proactive_sources = proactive_sources or []
        self._channel = channel
        self._lifecycle = lifecycle

    async def run(
        self,
        *,
        chat_id: str = "",
        base_score: float = 0.0,
        is_busy: bool = False,
    ) -> AgentTick:
        """执行完整主动检查，并在所有退出路径记录完成时间。"""

        tick = AgentTick(chat_id=chat_id, base_score=base_score)
        try:
            tick.phase_trace.append("gate")
            tick.gate_result = check_gate(
                chat_id=chat_id,
                is_busy=is_busy,
                state_store=self._state,
                any_action=self._any_action,
                cooldown=self._cooldown,
                base_score=base_score,
            )
            if not tick.gate_result.passed:
                logger.debug("主动准入阻止本轮检查: %s", tick.gate_result.reason)
                return await self._finish_tick(tick)

            tick.phase_trace.append("fetch")
            tick.gateway_result = await self._gateway.run()
            logger.info(
                "主动数据采集完成: alerts=%d content=%d context=%d errors=%d",
                len(tick.gateway_result.alerts),
                len(tick.gateway_result.content),
                len(tick.gateway_result.context),
                len(tick.gateway_result.errors),
            )

            if not tick.gateway_result.all_items and tick.gateway_result.errors:
                tick.judge_result = JudgeResult(
                    decision="skip",
                    evidence={
                        "reason": "source_error",
                        "errors": list(tick.gateway_result.errors),
                    },
                )
                logger.warning(
                    "主动检查因数据源故障跳过，不进入漂移: errors=%s",
                    tick.gateway_result.errors,
                )
                return await self._finish_tick(tick)

            drift_pipeline = self._drift
            if (
                self._should_enter_drift(tick.gateway_result)
                and drift_pipeline is not None
            ):
                tick.phase_trace.append("drift")
                connected_mcp = set(
                    getattr(self._mcp_pool, "connected_names", set())
                )
                drift_tick = await drift_pipeline.run(connected_mcp=connected_mcp)
                tick.drift_tick = drift_tick
                if drift_tick.finished and drift_tick.runs:
                    self._state.mark_drift_run()
                else:
                    logger.info(
                        "主动检查未执行漂移任务: skills=%d runs=%d finished=%s",
                        len(drift_tick.skills),
                        len(drift_tick.runs),
                        drift_tick.finished,
                    )
                if drift_tick.message:
                    tick.judge_result = JudgeResult(
                        decision="reply",
                        message=drift_tick.message,
                    )
                    await self._resolve_and_deliver(tick)
                return await self._finish_tick(tick)

            tick.phase_trace.append("judge")
            policy = self._state.get_policy(chat_id)
            tick.judge_result = await self._judge.evaluate(
                tick.gateway_result,
                chat_id,
                policy_topics=policy.topics,
            )
            logger.info(
                "主动内容评估完成: decision=%s cited=%d discarded=%d",
                tick.judge_result.decision,
                len(tick.judge_result.cited_item_ids),
                len(tick.judge_result.discarded_ids),
            )
            await self._resolve_and_deliver(tick)
            return await self._finish_tick(tick)
        finally:
            tick.finished_at = time.time()

    def replace_contributions(self, sources: list, lifecycle: ProactiveLifecycle) -> None:
        """替换下一代数据源和已编译模块图。"""

        self._gateway.replace_proactive_sources(sources)
        self._proactive_sources = list(sources)
        self._lifecycle = lifecycle

    async def _finish_tick(self, tick: AgentTick) -> AgentTick:
        """默认流程完成后运行扩展模块，不改变默认阶段的决策结果。"""

        if self._lifecycle is not None:
            context = ProactiveModuleContext(
                tick=tick,
                slots={"proactive:tick": tick},
            )
            await self._lifecycle.run(context)
        return tick

    async def _resolve_and_deliver(self, tick: AgentTick) -> None:
        """执行发送前解析，并在允许时完成出站投递。"""

        if tick.judge_result is None:
            return
        tick.phase_trace.append("resolve")
        tick.resolve_result = resolve_decision(
            tick.judge_result,
            state_store=self._state,
            chat_id=tick.chat_id,
            mcp_pool=self._mcp_pool,
            sources=self._proactive_sources,
            items=(
                tick.gateway_result.all_items
                if tick.gateway_result is not None
                else []
            ),
        )
        if tick.resolve_result.decision != "send":
            return
        tick.phase_trace.append("deliver")
        tick.deliver_result = await deliver_message(
            tick.resolve_result,
            chat_id=tick.chat_id,
            session_manager=self._session_manager,
            outbound_port=self._outbound_port,
            channel=self._channel,
        )

    def _should_enter_drift(self, gateway_result) -> bool:
        """仅在无告警和无内容且满足间隔时进入漂移。"""

        if self._drift is None or not self._drift_enabled:
            return False
        if gateway_result.alerts or gateway_result.content:
            return False
        last_run = self._state.get_drift_last_at()
        if last_run > 0 and (time.time() - last_run) < self._drift_min_interval:
            return False
        return True

    def close(self) -> None:
        """关闭主动与漂移链路拥有的持久化状态。"""

        if self._drift is not None and hasattr(self._drift, "close"):
            self._drift.close()
        self._state.close()

    async def start_extensions(self) -> None:
        """在外部资源连接完成后启动主动扩展模块。"""

        if self._lifecycle is not None:
            await self._lifecycle.start()

    async def stop_extensions(self) -> None:
        """在释放外部资源前停止主动扩展模块。"""

        if self._lifecycle is not None:
            await self._lifecycle.stop()

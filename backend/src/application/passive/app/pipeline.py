"""被动对话回合的六阶段流程编排。"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from application.agent.app.agent import Agent
from application.agent.domain.policies import DelegationPolicy
from application.capabilities.tools.registry import ToolRegistry
from application.memory.ports import MemoryPromptStore, MemoryQueryService
from application.passive.app.delivery import PassiveTurnDelivery
from application.passive.app.phase import PhaseModule, TurnFlow
from application.passive.app.prompt import PromptRenderer
from application.passive.app.reasoning import PassiveReasoner
from application.passive.domain.messages import IncomingMessage
from infra.bus.event import Event, EventBus
from infra.bus.message import MessageBus, OutboundPort
from infra.bus.types import MessageSender
from infra.telemetry import TraceRecorder

logger = logging.getLogger(__name__)


def _conversation_id_of(inbound: IncomingMessage) -> str:
    """读取统一被动消息协议中的会话标识。"""

    return inbound.conversation_id


class PassiveTurnPipeline:
    """按六个阶段编排一轮被动对话。"""

    def __init__(
        self,
        agent: Agent,
        tool_registry: ToolRegistry,
        message_bus: MessageBus | None = None,
        event_bus: EventBus | None = None,
        outbound_port: OutboundPort | None = None,
        memory_engine: MemoryQueryService | None = None,
        markdown_store: MemoryPromptStore | None = None,
        retrieval_max_items: int = 6,
        max_tool_steps: int = 5,
        recorder: TraceRecorder | None = None,
        delegation_policy: DelegationPolicy | None = None,
        tool_selection_max: int = 8,
        enable_thinking: bool = False,
        phase_modules_provider: Callable[[], list[Any]] | None = None,
        tool_hook_executor=None,
        message_sender: MessageSender | None = None,
    ) -> None:
        self.agent = agent
        self.tool_registry = tool_registry
        self.message_bus = message_bus
        self.event_bus = event_bus
        self.outbound_port = outbound_port or (
            message_bus.outbound_port if message_bus is not None else None
        )
        self.memory_engine = memory_engine
        self.markdown_store = markdown_store
        self.retrieval_max_items = retrieval_max_items
        self.max_tool_steps = max_tool_steps
        self.enable_thinking = enable_thinking
        self.recorder = recorder
        self.delegation_policy = delegation_policy or DelegationPolicy()
        self.tool_selection_max = max(1, tool_selection_max)
        self._phase_modules: list[PhaseModule] = []
        self._phase_modules_provider = phase_modules_provider
        self._tool_hook_executor = tool_hook_executor
        self.message_sender = message_sender

        self._prompt_renderer = PromptRenderer(
            agent=agent,
            tool_registry=tool_registry,
            memory_engine=memory_engine,
            markdown_store=markdown_store,
            retrieval_max_items=retrieval_max_items,
            tool_selection_max=tool_selection_max,
        )
        self._reasoner_component = PassiveReasoner(
            agent=agent,
            tool_registry=tool_registry,
            event_bus=event_bus,
            max_tool_steps=max_tool_steps,
            enable_thinking=enable_thinking,
            recorder=recorder,
            tool_hook_executor=tool_hook_executor,
        )
        self._delivery = PassiveTurnDelivery(
            agent=agent,
            event_bus=event_bus,
            message_bus=message_bus,
            outbound_port=self.outbound_port,
            message_sender=message_sender,
        )

    def register_phase_module(self, module: PhaseModule) -> None:
        """注册一个阶段模块（插件）。"""

        if module not in self._phase_modules:
            self._phase_modules.append(module)
            logger.info("phase module registered: %s", module.name)

    def process(self, inbound: IncomingMessage) -> None:
        """同步处理一条入站消息。"""

        flow = self._create_flow(inbound)
        turn_started = time.perf_counter()
        flow.extensions["_turn_started_at"] = turn_started
        self._record_event(
            {
                "type": "turn_start",
                "trace_id": flow.trace_id,
                "session_id": flow.session_id,
                "user_input": flow.user_input,
            }
        )
        logger.info("turn start session=%s", flow.session_id)

        try:
            self._call_phase_modules(flow, "on_turn_started")
            flow = self._run_phase(flow, "before_turn", self._before_turn)
            flow = self._run_phase(flow, "before_reasoning", self._before_reasoning)
            flow = self._run_phase(flow, "prompt_render", self._prompt_render)
            flow = self._run_phase(flow, "reasoner", self._reasoner)
            flow = self._run_phase(flow, "after_reasoning", self._after_reasoning)
            flow = self._run_phase(flow, "after_turn", self._after_turn)
            self._record_turn_end(flow, turn_started)
        except Exception as exc:
            self._record_turn_error(flow, exc)
            logger.exception("turn error session=%s", flow.session_id)
            self._send_error_reply(flow, exc)

    async def process_async(self, inbound: IncomingMessage) -> None:
        """异步处理一条入站消息，使模型等待不会阻塞其他会话。"""

        flow = self._create_flow(inbound)
        turn_started = time.perf_counter()
        flow.extensions["_turn_started_at"] = turn_started
        self._record_event(
            {
                "type": "turn_start",
                "trace_id": flow.trace_id,
                "session_id": flow.session_id,
                "user_input": flow.user_input,
            }
        )
        try:
            self._call_phase_modules(flow, "on_turn_started")
            flow = self._run_phase(flow, "before_turn", self._before_turn)
            flow = self._run_phase(flow, "before_reasoning", self._before_reasoning)
            flow = self._run_phase(flow, "prompt_render", self._prompt_render)
            flow = await self._reasoner_async(flow)
            flow = self._run_phase(flow, "after_reasoning", self._after_reasoning)
            flow = self._run_phase(flow, "after_turn", self._after_turn)
            self._record_turn_end(flow, turn_started)
        except Exception as exc:
            self._record_turn_error(flow, exc)
            logger.exception("async turn error session=%s", flow.session_id)
            self._send_error_reply(flow, exc)

    def _create_flow(self, inbound: IncomingMessage) -> TurnFlow:
        flow = TurnFlow(
            user_input=inbound.text,
            session_id=_conversation_id_of(inbound),
            channel=inbound.channel,
            inbound_metadata=dict(inbound.metadata),
            chat_id=inbound.chat_id or _conversation_id_of(inbound),
            trace_id=uuid4().hex[:12],
        )
        flow.inbound_metadata["media"] = list(inbound.media)
        flow.extensions["_phase_modules"] = self._phase_module_snapshot()
        return flow

    def _record_turn_end(self, flow: TurnFlow, turn_started: float) -> None:
        full_reply_latency_ms = round((time.perf_counter() - turn_started) * 1000, 2)
        self._record_event(
            {
                "type": "turn_end",
                "trace_id": flow.trace_id,
                "session_id": flow.session_id,
                "assistant_output": flow.final_output,
                "tool_trace": flow.tool_trace,
            }
        )
        logger.info("turn end session=%s", flow.session_id)
        self._record_event(
            {
                "type": "turn_perf",
                "trace_id": flow.trace_id,
                "session_id": flow.session_id,
                "latency_ms": full_reply_latency_ms,
                "full_reply_latency_ms": full_reply_latency_ms,
                "first_token_latency_ms": flow.extensions.get(
                    "first_token_latency_ms"
                ),
            }
        )

    def _record_turn_error(self, flow: TurnFlow, exc: Exception) -> None:
        self._record_event(
            {
                "type": "turn_error",
                "trace_id": flow.trace_id,
                "session_id": flow.session_id,
                "error": str(exc),
                "error_type": type(exc).__name__,
            }
        )

    def _before_turn(self, flow: TurnFlow) -> TurnFlow:
        self._call_phase_modules(flow, "on_before_turn")
        return flow

    def _before_reasoning(self, flow: TurnFlow) -> TurnFlow:
        self._call_phase_modules(flow, "on_before_reasoning")
        return flow

    def _prompt_render(self, flow: TurnFlow) -> TurnFlow:
        self._call_phase_modules(flow, "on_prompt_render")
        return self._prompt_renderer.render(flow)

    def _build_memory_block(self, session_id: str, user_input: str = "") -> str:
        return self._prompt_renderer.build_memory_block(session_id, user_input)

    def _reasoner(self, flow: TurnFlow) -> TurnFlow:
        self._call_phase_modules(flow, "on_reasoner")
        return self._reasoner_component.run_sync(flow)

    async def _reasoner_async(self, flow: TurnFlow) -> TurnFlow:
        self._call_phase_modules(flow, "on_reasoner")
        return await self._reasoner_component.run_async(flow)

    def _after_reasoning(self, flow: TurnFlow) -> TurnFlow:
        self._call_phase_modules(flow, "on_after_reasoning")
        return flow

    def _after_turn(self, flow: TurnFlow) -> TurnFlow:
        logger.info(
            "after_turn: final_output=%s",
            flow.final_output[:100] if flow.final_output else "EMPTY",
        )
        if not flow.final_output.strip():
            logger.error(
                "模型未生成有效回复，使用空回复兜底文案: trace=%s",
                flow.trace_id,
            )
            flow.final_output = "抱歉，本轮没有生成有效回复，请再试一次。"
        self._delivery.commit_and_send(flow)
        self._call_phase_modules(flow, "on_after_turn")
        return flow

    def _broadcast_turn_committed(self, flow: TurnFlow) -> None:
        self._delivery.broadcast_turn_committed(flow)

    def _send_outbound_reply(self, flow: TurnFlow) -> None:
        self._delivery.send_outbound_reply(flow)

    def _send_error_reply(self, flow: TurnFlow, exc: Exception) -> None:
        self._delivery.send_error_reply(flow, exc)

    def _tool_input_for_flow(self, tool_call, flow: TurnFlow) -> dict[str, Any]:
        """保留工具上下文规范化入口，具体规则归属推理组件。"""

        return PassiveReasoner._tool_input_for_flow(tool_call, flow)

    def _phase_module_snapshot(self) -> list[Any]:
        modules = list(self._phase_modules)
        if self._phase_modules_provider is not None:
            for module in self._phase_modules_provider():
                if module not in modules:
                    modules.append(module)
        return modules

    def _call_phase_modules(self, flow: TurnFlow, method_name: str) -> None:
        modules = flow.extensions.get("_phase_modules", [])
        for module in modules:
            handler = getattr(module, method_name, None)
            if not callable(handler):
                continue
            try:
                handler(flow)
            except Exception:
                logger.exception(
                    "phase module %s %s failed",
                    getattr(module, "name", type(module).__name__),
                    method_name,
                )

    def _run_phase(self, flow: TurnFlow, phase: str, fn):
        started = time.perf_counter()
        if not phase.startswith("after_"):
            self._publish_phase_event(flow, phase)
        self._record_event(
            {
                "type": "turn_phase_start",
                "phase": phase,
                "trace_id": flow.trace_id,
                "session_id": flow.session_id,
            }
        )
        try:
            result = fn(flow)
            if phase.startswith("after_"):
                self._publish_phase_event(result, phase)
            self._record_event(
                {
                    "type": "turn_phase_end",
                    "phase": phase,
                    "trace_id": flow.trace_id,
                    "session_id": flow.session_id,
                    "status": "ok",
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            )
            return result
        except Exception as exc:
            self._record_event(
                {
                    "type": "turn_phase_error",
                    "phase": phase,
                    "trace_id": flow.trace_id,
                    "session_id": flow.session_id,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            )
            raise

    def _publish_phase_event(self, flow: TurnFlow, phase: str) -> None:
        if self.event_bus is None:
            return
        self.event_bus.publish(
            Event(
                event_type=phase,
                trace_id=flow.trace_id,
                session_id=flow.session_id,
                payload={
                    "user_input": flow.user_input,
                    "assistant_output": flow.final_output,
                    "channel": flow.channel,
                    "flow": flow,
                },
            )
        )

    def _record_event(self, event: dict[str, Any]) -> None:
        if self.recorder is not None:
            self.recorder.record(event)

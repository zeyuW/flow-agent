"""被动对话回合管道：六个阶段串行处理一轮对话。

阶段顺序：
  TurnStarted → BeforeTurn → BeforeReasoning → PromptRender → Reasoner → AfterReasoning → AfterTurn

AfterTurn 阶段顺序（确保正确性）：
  ① EventBus.fanout(TurnCommitted) - 先广播事件让观察者处理
  ② OutboundPort.send(OutboundDispatch) - 后通过出站接口投递回复
  如果先发送回复再广播事件，一旦发送失败会导致状态不一致。
"""

import logging
import time
from uuid import uuid4
from typing import Any

from flow_agent.core.agent import Agent
from flow_agent.core.context_store import ContextStore
from flow_agent.core.delegation import DelegationPolicy
from flow_agent.core.phase_module import PhaseModule, TurnFlow
from flow_agent.channels.models import InboundMessage, OutboundMessage
from flow_agent.infra.trace import TraceRecorder
from flow_agent.llm.client import LLMToolCall
from flow_agent.memory.organizer import MemoryOrganizer
from flow_agent.memory.retriever import MemoryRetriever
from flow_agent.tools.registry import ToolRegistry
from flow_agent.dashboard.store import InMemoryDashboardStore
from flow_agent.messaging.event_bus import EventBus, TurnCommitted
from flow_agent.messaging.message_bus import MessageBus, OutboundDispatch, OutboundPort, BusOutboundPort

logger = logging.getLogger(__name__)


class PassiveTurnPipeline:
    """被动对话回合管道。

    六个阶段串行处理，每个阶段之前会调用所有 PhaseModule 的对应钩子。
    最后一个阶段 AfterTurn 负责：
    ① 通过 EventBus 广播 TurnCommitted 事件
    ② 通过 OutboundPort 投递出站回复
    """

    def __init__(
        self,
        agent: Agent,
        tool_registry: ToolRegistry,
        message_bus: MessageBus | None = None,
        event_bus: EventBus | None = None,
        outbound_port: OutboundPort | None = None,
        retriever: MemoryRetriever | None = None,
        retrieval_max_items: int = 6,
        max_tool_steps: int = 5,
        recorder: TraceRecorder | None = None,
        organizer: MemoryOrganizer | None = None,
        dashboard: InMemoryDashboardStore | None = None,
        delegation_policy: DelegationPolicy | None = None,
        tool_selection_max: int = 8,
    ) -> None:
        self.agent = agent
        self.tool_registry = tool_registry
        self.message_bus = message_bus
        self.event_bus = event_bus
        # 出站接口：优先使用 outbound_port，否则从 message_bus 获取
        self.outbound_port = outbound_port or (
            message_bus.outbound_port if message_bus is not None else None
        )
        self.retriever = retriever
        self.retrieval_max_items = retrieval_max_items
        self.max_tool_steps = max_tool_steps
        self.recorder = recorder
        self.organizer = organizer
        self.dashboard = dashboard
        self.delegation_policy = delegation_policy or DelegationPolicy()
        self.tool_selection_max = max(1, tool_selection_max)
        self.context_store = ContextStore(
            agent=agent,
            retriever=retriever,
            retrieval_max_items=retrieval_max_items,
        )
        self._phase_modules: list[PhaseModule] = []

    def register_phase_module(self, module: PhaseModule) -> None:
        """注册一个阶段模块（插件）。"""
        if module not in self._phase_modules:
            self._phase_modules.append(module)
            logger.info("phase module registered: %s", module.name)

    def process(self, inbound: InboundMessage) -> None:
        """处理一条入站消息，执行完整的六阶段管道。

        这是 AgentLoop 调用的入口。
        管道处理完成后：
        ① 通过 EventBus 广播 TurnCommitted 事件
        ② 通过 OutboundPort 投递回复到 MessageBus 出站队列

        顺序确保事件先于回复发送，避免状态不一致。
        """
        flow = TurnFlow(
            user_input=inbound.text,
            session_id=inbound.session_id,
            channel=inbound.channel,
            trace_id=uuid4().hex[:12],
        )
        self.agent.set_session(flow.session_id)

        turn_started = time.perf_counter()
        self._record_event({
            "type": "turn_start",
            "trace_id": flow.trace_id,
            "session_id": flow.session_id,
            "user_input": flow.user_input,
        })
        logger.info("turn start session=%s", flow.session_id)

        try:
            # Phase 0: TurnStarted (notify phase modules)
            for module in self._phase_modules:
                try:
                    module.on_turn_started(flow)
                except Exception:
                    logger.exception("phase module %s on_turn_started failed", module.name)

            # Phase 1: BeforeTurn
            flow = self._run_phase(flow, "before_turn", self._before_turn)

            # Phase 2: BeforeReasoning
            flow = self._run_phase(flow, "before_reasoning", self._before_reasoning)

            # Phase 3: PromptRender
            flow = self._run_phase(flow, "prompt_render", self._prompt_render)

            # Phase 4: Reasoner
            flow = self._run_phase(flow, "reasoner", self._reasoner)

            # Phase 5: AfterReasoning
            flow = self._run_phase(flow, "after_reasoning", self._after_reasoning)

            # Phase 6: AfterTurn — ① 广播事件 ② 发送回复
            flow = self._run_phase(flow, "after_turn", self._after_turn)

            self._record_event({
                "type": "turn_end",
                "trace_id": flow.trace_id,
                "session_id": flow.session_id,
                "assistant_output": flow.final_output,
                "tool_trace": flow.tool_trace,
            })
            logger.info("turn end session=%s", flow.session_id)
            self._record_event({
                "type": "turn_perf",
                "trace_id": flow.trace_id,
                "session_id": flow.session_id,
                "latency_ms": round((time.perf_counter() - turn_started) * 1000, 2),
            })
        except Exception as exc:
            self._record_event({
                "type": "turn_error",
                "trace_id": flow.trace_id,
                "session_id": flow.session_id,
                "error": str(exc),
                "error_type": type(exc).__name__,
            })
            logger.exception("turn error session=%s", flow.session_id)
            # 即使出错也尝试发送错误回复
            self._send_error_reply(flow, exc)

    # ── 阶段钩子 ────────────────────────────────────────────

    def _before_turn(self, flow: TurnFlow) -> TurnFlow:
        return flow

    def _before_reasoning(self, flow: TurnFlow) -> TurnFlow:
        for module in self._phase_modules:
            try:
                module.on_before_reasoning(flow)
            except Exception:
                logger.exception("phase module %s on_before_reasoning failed", module.name)
        return flow

    def _prompt_render(self, flow: TurnFlow) -> TurnFlow:
        """组装提示词阶段。

        构建 persona、memory、retrieval 块，组装最终的 messages。
        """
        for module in self._phase_modules:
            try:
                module.on_prompt_render(flow)
            except Exception:
                logger.exception("phase module %s on_prompt_render failed", module.name)

        # 构建 persona 块
        persona_block = self._build_persona_block(proactive=False, channel=flow.channel)

        # 构建 memory 块
        memory_block = self._build_memory_block(flow.session_id)

        # 构建 retrieval 块
        retrieval_block = self._build_retrieval_block(flow.user_input)

        # 构建工具说明
        tools = self.tool_registry.list_openai_tools()
        flow.tools = tools[:self.tool_selection_max] if tools else []

        names = [t.get("function", {}).get("name", "") for t in flow.tools]
        tool_instructions = (
            f"可用工具: {chr(10).join(names) if names else '无'}\n\n"
            f"当需要获取外部信息时，请使用工具函数调用。"
        )

        messages = self.agent.build_turn_messages(
            user_input=flow.user_input,
            persona_block=persona_block,
            memory_block=memory_block,
            retrieval_block=retrieval_block,
            tool_instructions=tool_instructions,
        )
        flow.messages = messages
        return flow

    def _build_persona_block(self, proactive: bool, channel: str) -> str:
        """构建人设块。"""
        if self.agent.persona_resolver is not None:
            persona = self.agent.persona_resolver.resolve(
                proactive=proactive,
                channel=channel,
                mode="passive",
            )
            return persona.to_prompt_block()
        return ""

    def _build_memory_block(self, session_id: str) -> str:
        """构建记忆块。"""
        history = self.agent.context.get_history(session_id)
        if not history:
            return ""
        lines = ["## 近期对话回顾"]
        for msg in history[-6:]:
            role = msg.get("role", "unknown")
            content = str(msg.get("content", ""))[:200]
            label = "用户" if role == "user" else "助手"
            lines.append(f"- {label}: {content}")
        return "\n".join(lines)

    def _build_retrieval_block(self, user_input: str) -> str:
        """构建检索块。"""
        if self.retriever is None:
            return ""
        try:
            memories = self.retriever.retrieve(user_input, max_items=self.retrieval_max_items)
            if not memories:
                return ""
            lines = ["## 相关记忆"]
            for m in memories:
                lines.append(f"- {m.content}")
            return "\n".join(lines)
        except Exception:
            logger.exception("retrieval failed")
            return ""

    def _reasoner(self, flow: TurnFlow) -> TurnFlow:
        return self._run_tool_loop(flow)

    def _after_reasoning(self, flow: TurnFlow) -> TurnFlow:
        for module in self._phase_modules:
            try:
                module.on_after_reasoning(flow)
            except Exception:
                logger.exception("phase module %s on_after_reasoning failed", module.name)
        return flow

    def _after_turn(self, flow: TurnFlow) -> TurnFlow:
        """AfterTurn 阶段：顺序执行 ① 事件广播 ② 出站投递。

        顺序很重要：
        - 先广播 TurnCommitted 事件，让记忆系统等观察者处理
        - 再通过 OutboundPort 发送回复，确保回复发送的可靠性
        - 如果先发送后广播，发送失败会导致状态不一致
        """
        # 记忆持久化
        self.context_store.commit(
            user_input=flow.user_input,
            assistant_output=flow.final_output,
        )
        if self.organizer is not None:
            try:
                stats = self.organizer.organize(flow.session_id)
                self._record_event({
                    "type": "memory_organize",
                    "trace_id": flow.trace_id,
                    "session_id": flow.session_id,
                    **stats,
                })
            except Exception:
                logger.exception("memory organize failed")

        # ① 先广播 TurnCommitted 事件
        self._broadcast_turn_committed(flow)

        # ② 再通过 OutboundPort 投递出站回复
        self._send_outbound_reply(flow)

        # 通知阶段模块
        for module in self._phase_modules:
            try:
                module.on_after_turn(flow)
            except Exception:
                logger.exception("phase module %s on_after_turn failed", module.name)

        return flow

    def _broadcast_turn_committed(self, flow: TurnFlow) -> None:
        """通过 EventBus 广播 TurnCommitted 事件。

        事件包含本轮对话的所有元数据：
        - user_input: 用户输入
        - assistant_output: 助手回复
        - tool_trace: 工具调用链
        - token 统计等
        """
        if self.event_bus is None:
            return

        event = TurnCommitted(
            trace_id=flow.trace_id,
            session_id=flow.session_id,
            user_input=flow.user_input,
            assistant_output=flow.final_output,
            tool_trace=flow.tool_trace,
        )
        # 附加额外元数据
        event.payload["channel"] = flow.channel
        event.payload["token_stats"] = {
            "tool_steps": len(flow.tool_trace),
        }

        try:
            self.event_bus.publish(event)
            logger.debug("turn_committed event broadcast: trace=%s", flow.trace_id)
        except Exception:
            logger.exception("failed to broadcast TurnCommitted event")

    def _send_outbound_reply(self, flow: TurnFlow) -> None:
        """通过 OutboundPort 投递出站回复。

        将管道的 final_output 封装为 OutboundDispatch，
        通过 outbound_port.send() 投递到 MessageBus 出站队列。
        MessageBus 后台 dispatch_outbound 任务会分发给对应渠道。
        """
        if self.outbound_port is None:
            logger.warning("no outbound_port configured, cannot send reply")
            return

        dispatch = OutboundDispatch(
            channel=flow.channel,
            session_id=flow.session_id,
            text=flow.final_output,
            metadata={
                "trace_id": flow.trace_id,
                "tool_trace": flow.tool_trace,
            },
        )

        try:
            self.outbound_port.send(dispatch)
            logger.debug("outbound reply dispatched: channel=%s session=%s", flow.channel, flow.session_id)
        except Exception:
            logger.exception("failed to dispatch outbound reply")

    def _send_error_reply(self, flow: TurnFlow, exc: Exception) -> None:
        """发送错误回复。"""
        if self.outbound_port is None:
            return
        dispatch = OutboundDispatch(
            channel=flow.channel,
            session_id=flow.session_id,
            text=f"处理消息时出错: {exc}",
            metadata={"trace_id": flow.trace_id, "error": True},
        )
        try:
            self.outbound_port.send(dispatch)
        except Exception:
            logger.exception("failed to send error reply")

    # ── 工具调用循环 ────────────────────────────────────────

    def _run_tool_loop(self, flow: TurnFlow) -> TurnFlow:
        current_messages = list(flow.messages)
        loop_started = time.perf_counter()
        for step in range(self.max_tool_steps):
            result = self.agent.generate_from_messages(
                current_messages,
                tools=flow.tools if flow.tools else None,
            )
            if not result.tool_calls:
                flow.final_output = result.content or ""
                self._record_event({
                    "type": "tool_loop_perf",
                    "trace_id": flow.trace_id,
                    "session_id": flow.session_id,
                    "steps": step,
                    "latency_ms": round((time.perf_counter() - loop_started) * 1000, 2),
                })
                return flow
            current_messages.append({
                "role": "assistant",
                "content": result.content or "",
                "tool_calls": [self._tool_call_to_message_item(tc) for tc in result.tool_calls],
            })
            for tool_call in result.tool_calls:
                tool_result = self.tool_registry.execute(
                    tool_name=tool_call.name,
                    tool_input=tool_call.arguments,
                )
                tool_message = f"Tool `{tool_call.name}` ok={tool_result.ok}: {tool_result.content}"
                flow.tool_trace.append({
                    "step": str(step + 1),
                    "tool": tool_call.name,
                    "status": "ok" if tool_result.ok else "failed",
                })
                current_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_message,
                })
        flow.final_output = "工具调用次数超过上限，请调整请求后重试。"
        self._record_event({
            "type": "tool_loop_perf",
            "trace_id": flow.trace_id,
            "session_id": flow.session_id,
            "steps": self.max_tool_steps,
            "latency_ms": round((time.perf_counter() - loop_started) * 1000, 2),
        })
        return flow

    def _tool_call_to_message_item(self, tool_call: LLMToolCall) -> dict[str, Any]:
        return {
            "id": tool_call.id,
            "type": "function",
            "function": {
                "name": tool_call.name,
                "arguments": tool_call.arguments_json,
            },
        }

    # ── 辅助方法 ────────────────────────────────────────────

    def _run_phase(self, flow: TurnFlow, phase: str, fn):
        started = time.perf_counter()
        self._record_event({
            "type": "turn_phase_start",
            "phase": phase,
            "trace_id": flow.trace_id,
            "session_id": flow.session_id,
        })
        try:
            result = fn(flow)
            self._record_event({
                "type": "turn_phase_end",
                "phase": phase,
                "trace_id": flow.trace_id,
                "session_id": flow.session_id,
                "status": "ok",
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            })
            return result
        except Exception as exc:
            self._record_event({
                "type": "turn_phase_error",
                "phase": phase,
                "trace_id": flow.trace_id,
                "session_id": flow.session_id,
                "error": str(exc),
                "error_type": type(exc).__name__,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            })
            raise

    def _record_event(self, event: dict[str, Any]) -> None:
        if self.dashboard is not None:
            try:
                self.dashboard.record(event)
            except Exception:
                logger.exception("dashboard record failed")
        if self.recorder is not None:
            self.recorder.record(event)
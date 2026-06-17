"""被动对话回合管道：六个阶段串行处理一轮对话。

阶段顺序：
  BeforeTurn → BeforeReasoning → PromptRender → Reasoner → AfterReasoning → AfterTurn

AfterTurn 收尾双动作（并行）：
  ① EventBus.fanout(TurnCommitted) - 事件广播
  ② MessageBus.dispatch_outbound(OutboundMessage) - 回复投递
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
from flow_agent.messaging.message_bus import MessageBus

logger = logging.getLogger(__name__)


class PassiveTurnPipeline:
    """被动对话回合管道。

    六个阶段串行处理，每个阶段之前会调用所有 PhaseModule 的对应钩子。
    最后一个阶段 AfterTurn 负责并行触发 EventBus 广播和 MessageBus 出站投递。
    """

    def __init__(
        self,
        agent: Agent,
        tool_registry: ToolRegistry,
        message_bus: MessageBus,
        event_bus: EventBus,
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
        管道处理完成后，通过 MessageBus 投递回复，通过 EventBus 广播事件。
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

            # Phase 6: AfterTurn — 收尾双动作
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
            # 即使出错，也尝试发送错误回复
            error_msg = OutboundMessage(
                channel=flow.channel,
                session_id=flow.session_id,
                text=f"处理请求时发生错误: {exc}",
            )
            self.message_bus.dispatch_outbound(error_msg)

    # ── 六个阶段 ────────────────────────────────────────────

    def _before_turn(self, flow: TurnFlow) -> TurnFlow:
        """BeforeTurn: 回合准备 — 委托决策。"""
        for mod in self._phase_modules:
            try:
                mod.on_before_turn(flow)
            except Exception:
                logger.exception("phase module %s failed in before_turn", mod.name)
        decision = self.delegation_policy.decide(
            user_input=flow.user_input,
            tool_step_budget=self.max_tool_steps,
        )
        flow.extensions["delegation_decision"] = decision.action
        logger.debug("delegation decision: %s", decision.action)
        return flow

    def _before_reasoning(self, flow: TurnFlow) -> TurnFlow:
        """BeforeReasoning: 推理前准备 — 记忆检索、上下文构造。"""
        for mod in self._phase_modules:
            try:
                mod.on_before_reasoning(flow)
            except Exception:
                logger.exception("phase module %s failed in before_reasoning", mod.name)
        bundle = self.context_store.prepare(
            session_id=flow.session_id,
            user_input=flow.user_input,
        )
        flow.retrieval_trace = bundle.retrieval_trace
        if bundle.retrieved:
            flow.memory_block = "Relevant memory:\n" + "\n".join(
                f"- {m.content}" for m in bundle.retrieved
            )
        return flow

    def _prompt_render(self, flow: TurnFlow) -> TurnFlow:
        """PromptRender: 提示词组装 — 构建 messages 和 tools。"""
        for mod in self._phase_modules:
            try:
                mod.on_prompt_render(flow)
            except Exception:
                logger.exception("phase module %s failed in prompt_render", mod.name)
        flow = self._build_prompt(flow)
        return flow

    def _reasoner(self, flow: TurnFlow) -> TurnFlow:
        """Reasoner: 推理执行 — 调用 LLM，处理工具调用循环。"""
        flow = self._run_tool_loop(flow)
        return flow

    def _after_reasoning(self, flow: TurnFlow) -> TurnFlow:
        """AfterReasoning: 推理后处理 — 持久化、记忆整理。"""
        for mod in self._phase_modules:
            try:
                mod.on_after_reasoning(flow)
            except Exception:
                logger.exception("phase module %s failed in after_reasoning", mod.name)
        self.context_store.commit(
            user_input=flow.user_input,
            assistant_output=flow.final_output,
        )
        if self.organizer is not None:
            stats = self.organizer.organize(flow.session_id)
            self._record_event({
                "type": "memory_organize",
                "trace_id": flow.trace_id,
                "session_id": flow.session_id,
                **stats,
            })
        return flow

    def _after_turn(self, flow: TurnFlow) -> TurnFlow:
        """AfterTurn: 收尾双动作 — EventBus 广播 + MessageBus 出站投递。

        这两个动作独立并行：
        ① 构建 TurnCommitted 事件，通过 EventBus.fanout 扇出给所有订阅者
        ② 构建 OutboundMessage，通过 MessageBus.dispatch_outbound 投递到出站队列
        """
        for mod in self._phase_modules:
            try:
                mod.on_after_turn(flow)
            except Exception:
                logger.exception("phase module %s failed in after_turn", mod.name)

        # 动作 ①：事件广播（EventBus fanout）
        event = TurnCommitted(
            trace_id=flow.trace_id,
            session_id=flow.session_id,
            user_input=flow.user_input,
            assistant_output=flow.final_output,
            tool_trace=flow.tool_trace,
        )
        self.event_bus.publish(event)

        # 动作 ②：回复投递（MessageBus outbound）
        outbound = OutboundMessage(
            channel=flow.channel,
            session_id=flow.session_id,
            text=flow.final_output,
        )
        outbound.metadata["trace_id"] = flow.trace_id
        outbound.metadata["tool_trace"] = flow.tool_trace
        self.message_bus.dispatch_outbound(outbound)

        return flow

    # ── 提示词构建 ──────────────────────────────────────────

    def _build_prompt(self, flow: TurnFlow) -> TurnFlow:
        persona_block = ""
        if self.agent.persona_resolver is not None:
            persona_block = self.agent.persona_resolver.render_block(
                channel=flow.channel,
                proactive_mode=False,
            ) or ""
        memory_block = flow.memory_block or ""
        retrieval_block = ""
        if flow.retrieval_trace:
            items = int(flow.retrieval_trace[0].get("items", "0"))
            if items > 0:
                retrieval_block = f"[检索到 {items} 条记忆]"

        # 使用 ToolRegistry 的 select_openai_tools
        tools: list[dict[str, Any]] = []
        if self.tool_registry.list_tool_names():
            tools = self.tool_registry.select_openai_tools(
                flow.user_input,
                max_tools=self.tool_selection_max,
            )

        tool_instructions = ""
        if tools:
            names = [t.get("function", {}).get("name", "?") for t in tools]
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
        flow.tools = tools
        return flow

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
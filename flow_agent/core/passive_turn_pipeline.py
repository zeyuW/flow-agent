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
from datetime import datetime
from uuid import uuid4
from typing import Any
from collections.abc import Callable

from flow_agent.core.agent import Agent
from flow_agent.core.delegation import DelegationPolicy
from flow_agent.core.phase_module import PhaseModule, TurnFlow
from flow_agent.channels.models import InboundMessage, OutboundMessage
from flow_agent.infra.trace import TraceRecorder
from flow_agent.llm.client import LLMToolCall
from flow_agent.memory.memory_engine import MemoryEngine
from flow_agent.memory.markdown_store import MarkdownStore
from flow_agent.tools.registry import ToolRegistry
from flow_agent.messaging.event_bus import Event, EventBus, TurnCommitted, StreamDeltaReady, ToolCallStarted, ToolCallCompleted
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
        memory_engine: MemoryEngine | None = None,
        markdown_store: MarkdownStore | None = None,
        retrieval_max_items: int = 6,
        max_tool_steps: int = 5,
        recorder: TraceRecorder | None = None,
        delegation_policy: DelegationPolicy | None = None,
        tool_selection_max: int = 8,
        enable_thinking: bool = False,
        phase_modules_provider: Callable[[], list[Any]] | None = None,
        tool_hook_executor=None,
    ) -> None:
        self.agent = agent
        self.tool_registry = tool_registry
        self.message_bus = message_bus
        self.event_bus = event_bus
        # 出站接口：优先使用 outbound_port，否则从 message_bus 获取
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
            inbound_metadata=inbound.metadata or {},  # 保存入站 metadata
            trace_id=uuid4().hex[:12],
        )
        flow.extensions["_phase_modules"] = self._phase_module_snapshot()
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
            self._call_phase_modules(flow, "on_turn_started")

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
        self._call_phase_modules(flow, "on_before_turn")
        return flow

    def _before_reasoning(self, flow: TurnFlow) -> TurnFlow:
        self._call_phase_modules(flow, "on_before_reasoning")
        return flow

    def _prompt_render(self, flow: TurnFlow) -> TurnFlow:
        """组装提示词阶段。

        构建 persona、memory、retrieval 块，组装最终的 messages。
        """
        self._call_phase_modules(flow, "on_prompt_render")

        # 构建 persona 块
        persona_block = self._build_persona_block(proactive=False, channel=flow.channel)

        # 构建 memory 块
        memory_block = self._build_memory_block(flow.session_id, flow.user_input)

        # 构建工具说明
        flow.tools = self.tool_registry.select_openai_tools(
            flow.user_input,
            max_tools=self.tool_selection_max,
        )
        scheduled_execution = bool(flow.inbound_metadata.get("scheduled_task"))
        if scheduled_execution:
            blocked = {
                "schedule_task",
                "list_scheduled_tasks",
                "cancel_scheduled_task",
            }
            flow.tools = [
                item
                for item in flow.tools
                if item.get("function", {}).get("name") not in blocked
            ]

        names = [t.get("function", {}).get("name", "") for t in flow.tools]
        instructions = [
            f"当前系统时间: {datetime.now().astimezone().isoformat()}",
            f"可用工具: {chr(10).join(names) if names else '无'}",
            "当需要获取外部信息时，请使用工具函数调用。",
        ]
        if scheduled_execution:
            instructions.append(
                "当前消息是已经到期的定时任务，立即执行任务并报告结果，"
                "不要再次创建或修改定时任务。"
            )
        else:
            instructions.append(
                "当用户要求提醒、定时执行或周期任务时，必须调用 schedule_task，"
                "不得仅写入长期记忆，也不得声称系统无法定时唤醒。"
            )
            instructions.append(
                "当用户要求长时间不互动后主动联系、主动推送感兴趣内容或修改主动策略时，"
                "必须调用 configure_proactive_policy；未给出具体时长时默认使用 120 分钟并告知用户。"
                "查询当前策略时调用 get_proactive_status。"
            )
            instructions.append(
                "当用户要求执行插件提供的后台任务时，先调用 list_background_jobs 确认名称，"
                "再调用 run_background_job；需要查看进度或结果时调用 list_background_runs。"
                "后台任务不是 MCP 服务，不得使用 mcp_list 判断后台任务是否存在。"
                "回答时必须原样引用工具返回的 job_name，不得自行改写任务名称。"
            )
        tool_instructions = "\n\n".join(instructions)

        messages = self.agent.build_turn_messages(
            user_input=flow.user_input,
            persona_block=persona_block,
            memory_block=memory_block,
            retrieval_block="",
            tool_instructions=tool_instructions,
        )
        flow.messages = messages
        return flow

    def _build_persona_block(self, proactive: bool, channel: str) -> str:
        """构建人设块。"""
        if self.agent.persona_resolver is not None:
            return self.agent.persona_resolver.render_block(
                channel=channel,
                proactive_mode=proactive,
            )
        return ""

    def _build_memory_block(self, session_id: str, user_input: str = "") -> str:
        """构建由长期记忆和近期对话组成的提示词记忆块。"""
        blocks: list[str] = []

        # 稳定档案与压缩上下文先注入，待归档缓冲绝不进入提示词。
        if self.markdown_store is not None:
            try:
                markdown_block = self.markdown_store.render_prompt_memory()
                if markdown_block:
                    blocks.append(markdown_block)
            except Exception:
                logger.exception("Markdown 记忆提示词构建失败")

        # 长期记忆优先注入，使跨会话的偏好、规则和待办能够影响当前回复。
        if self.memory_engine is not None and user_input.strip():
            try:
                long_term_block = self.memory_engine.retrieve_for_prompt(
                    user_input,
                    max_items=self.retrieval_max_items,
                )
                if long_term_block:
                    blocks.append(long_term_block)
            except Exception:
                logger.exception("长期记忆检索失败")

        history = self.agent.context.get_history(session_id)
        if history:
            lines = ["## 近期对话回顾"]
            for msg in history[-6:]:
                role = msg.get("role", "unknown")
                content = str(msg.get("content", ""))[:200]
                label = "用户" if role == "user" else "助手"
                lines.append(f"- {label}: {content}")
            blocks.append("\n".join(lines))

        return "\n\n".join(blocks)

    def _reasoner(self, flow: TurnFlow) -> TurnFlow:
        self._call_phase_modules(flow, "on_reasoner")
        # 如果启用思考模式，使用流式生成
        if self.enable_thinking and self.event_bus:
            chat_id = flow.inbound_metadata.get("telegram_chat_id") if flow.inbound_metadata else ""
            if chat_id:
                # 发送初始状态
                self.event_bus.publish(StreamDeltaReady(
                    trace_id=flow.trace_id,
                    session_id=flow.session_id,
                    delta="🤔 正在思考...",
                    channel=flow.channel,
                    chat_id=str(chat_id),
                ))
                
                # 定义流式回调函数
                def on_delta(delta: str) -> None:
                    self.event_bus.publish(StreamDeltaReady(
                        trace_id=flow.trace_id,
                        session_id=flow.session_id,
                        delta=delta,
                        channel=flow.channel,
                        chat_id=str(chat_id),
                    ))
                
                # 使用流式生成（如果有流式方法）
                if hasattr(self.agent.llm_client, 'generate_stream'):
                    # 复用提示词渲染阶段的结果，避免流式分支丢失长期记忆和工具说明。
                    result = self.agent.llm_client.generate_stream(
                        messages=flow.messages,
                        tools=flow.tools,
                        on_delta=on_delta,
                    )

                    if getattr(result, "tool_calls", None):
                        # 流式首轮只完成工具选择，后续沿用同一个工具循环继续推理。
                        return self._run_tool_loop(flow, initial_result=result)
                    content = str(getattr(result, "content", "") or "")
                    if content.strip():
                        flow.final_output = content
                        return flow
                    logger.warning("流式推理返回空内容，改用普通工具循环")
        
        # 非思考模式或流式失败，使用正常流程
        return self._run_tool_loop(flow)

    def _after_reasoning(self, flow: TurnFlow) -> TurnFlow:
        self._call_phase_modules(flow, "on_after_reasoning")
        return flow

    def _after_turn(self, flow: TurnFlow) -> TurnFlow:
        """AfterTurn 阶段：顺序执行 ① 事件广播 ② 出站投递。

        顺序很重要：
        - 先广播 TurnCommitted 事件，让记忆系统等观察者处理
        - 再通过 OutboundPort 发送回复，确保回复发送的可靠性
        - 如果先发送后广播，发送失败会导致状态不一致
        """
        logger.info("after_turn: final_output=%s", flow.final_output[:100] if flow.final_output else "EMPTY")
        if not flow.final_output.strip():
            logger.error("模型未生成有效回复，使用空回复兜底文案: trace=%s", flow.trace_id)
            flow.final_output = "抱歉，本轮没有生成有效回复，请再试一次。"
        # 写入当前会话历史。
        self.agent.commit_turn(
            user_input=flow.user_input,
            assistant_output=flow.final_output,
        )

        # ① 先广播 TurnCommitted 事件
        self._broadcast_turn_committed(flow)

        # ② 再通过 OutboundPort 投递出站回复
        self._send_outbound_reply(flow)

        # 通知阶段模块
        self._call_phase_modules(flow, "on_after_turn")

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

        logger.info("sending outbound reply: channel=%s, text=%s", flow.channel, flow.final_output[:100])
        
        # 合并入站 metadata 和管道 metadata
        metadata = {
            "trace_id": flow.trace_id,
            "tool_trace": flow.tool_trace,
        }
        # 添加渠道特定的 metadata（如 telegram_chat_id）
        if flow.inbound_metadata:
            metadata.update(flow.inbound_metadata)
        
        dispatch = OutboundDispatch(
            channel=flow.channel,
            session_id=flow.session_id,
            text=flow.final_output,
            chat_id=str(
                flow.inbound_metadata.get("telegram_chat_id")
                or flow.inbound_metadata.get("qq_group_id")
                or flow.inbound_metadata.get("qq_user_id")
                or flow.session_id
            ),
            metadata=metadata,
        )

        try:
            self.outbound_port.send(dispatch)
            logger.debug("outbound reply dispatched: channel=%s session=%s metadata=%s", flow.channel, flow.session_id, list(metadata.keys()))
        except Exception:
            logger.exception("failed to dispatch outbound reply")

    def _send_error_reply(self, flow: TurnFlow, exc: Exception) -> None:
        """发送错误回复。"""
        if self.outbound_port is None:
            return
        metadata: dict[str, object] = {
            "trace_id": flow.trace_id,
            "error": True,
        }
        if flow.inbound_metadata:
            metadata.update(flow.inbound_metadata)
        dispatch = OutboundDispatch(
            channel=flow.channel,
            session_id=flow.session_id,
            text=f"处理消息时出错: {exc}",
            chat_id=str(
                flow.inbound_metadata.get("telegram_chat_id")
                or flow.inbound_metadata.get("qq_group_id")
                or flow.inbound_metadata.get("qq_user_id")
                or flow.session_id
            ),
            metadata=metadata,
        )
        try:
            self.outbound_port.send(dispatch)
        except Exception:
            logger.exception("failed to send error reply")

    # ── 工具调用循环 ────────────────────────────────────────

    def _run_tool_loop(
        self,
        flow: TurnFlow,
        initial_result=None,
    ) -> TurnFlow:
        """执行工具循环，并可复用流式首轮已经生成的工具调用。"""
        current_messages = list(flow.messages)
        loop_started = time.perf_counter()
        for step in range(self.max_tool_steps):
            if step == 0 and initial_result is not None:
                result = initial_result
            else:
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
                tool_input = dict(tool_call.arguments)
                if tool_call.name in {
                    "schedule_task",
                    "list_scheduled_tasks",
                    "cancel_scheduled_task",
                    "configure_proactive_policy",
                    "get_proactive_status",
                    "spawn",
                }:
                    tool_input["__session_id"] = flow.session_id
                    tool_input["__channel"] = flow.channel
                    tool_input["__chat_id"] = str(
                        flow.inbound_metadata.get("telegram_chat_id")
                        or flow.session_id
                    )
                if self._tool_hook_executor is not None:
                    outcome = self._tool_hook_executor.execute_sync(
                        tool_call.name,
                        tool_input,
                        flow.session_id,
                    )
                    if outcome.decision == "deny":
                        tool_message = (
                            f"Tool `{tool_call.name}` ok=False: "
                            f"插件钩子阻止执行: {outcome.reason}"
                        )
                        flow.tool_trace.append({
                            "step": str(step + 1),
                            "tool": tool_call.name,
                            "status": "blocked",
                            "arguments": tool_call.arguments_json,
                        })
                        current_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_message,
                        })
                        continue
                    if outcome.modified_args is not None:
                        tool_input = dict(outcome.modified_args)
                tool_result = self.tool_registry.execute(
                    tool_name=tool_call.name,
                    tool_input=tool_input,
                )
                tool_message = f"Tool `{tool_call.name}` ok={tool_result.ok}: {tool_result.content}"
                flow.tool_trace.append({
                    "step": str(step + 1),
                    "tool": tool_call.name,
                    "status": "ok" if tool_result.ok else "failed",
                    "arguments": tool_call.arguments_json,
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

    def _phase_module_snapshot(self) -> list[Any]:
        """在回合开始时冻结当前插件阶段模块。"""

        modules = list(self._phase_modules)
        if self._phase_modules_provider is not None:
            for module in self._phase_modules_provider():
                if module not in modules:
                    modules.append(module)
        return modules

    def _call_phase_modules(self, flow: TurnFlow, method_name: str) -> None:
        """调用当前回合快照中实现了指定钩子的阶段模块。"""

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
        if not phase.startswith("after_"):
            self._publish_phase_event(flow, phase)
        self._record_event({
            "type": "turn_phase_start",
            "phase": phase,
            "trace_id": flow.trace_id,
            "session_id": flow.session_id,
        })
        try:
            result = fn(flow)
            if phase.startswith("after_"):
                self._publish_phase_event(result, phase)
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

    def _publish_phase_event(self, flow: TurnFlow, phase: str) -> None:
        """在阶段语义对应的前置或后置时点广播插件生命周期事件。"""

        if self.event_bus is None:
            return
        self.event_bus.publish(Event(
            event_type=phase,
            trace_id=flow.trace_id,
            session_id=flow.session_id,
            payload={
                "user_input": flow.user_input,
                "assistant_output": flow.final_output,
                "channel": flow.channel,
                "flow": flow,
            },
        ))

    def _record_event(self, event: dict[str, Any]) -> None:
        if self.recorder is not None:
            self.recorder.record(event)

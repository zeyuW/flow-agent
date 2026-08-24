"""被动回合的模型推理和工具调用循环。"""

from __future__ import annotations

import logging
import time
from typing import Any

from application.agent.app.agent import Agent
from application.capabilities.llm.client import LLMToolCall, llm_stage
from application.capabilities.tools.registry import ToolRegistry
from application.passive.app.phase import TurnFlow
from infra.bus.event import EventBus, StreamDeltaReady
from infra.telemetry import TraceRecorder

logger = logging.getLogger(__name__)


class PassiveReasoner:
    """执行同步/异步模型调用，并负责完整的工具循环。"""

    def __init__(
        self,
        *,
        agent: Agent,
        tool_registry: ToolRegistry,
        event_bus: EventBus | None = None,
        max_tool_steps: int = 5,
        enable_thinking: bool = False,
        recorder: TraceRecorder | None = None,
        tool_hook_executor=None,
    ) -> None:
        self.agent = agent
        self.tool_registry = tool_registry
        self.event_bus = event_bus
        self.max_tool_steps = max_tool_steps
        self.enable_thinking = enable_thinking
        self.recorder = recorder
        self.tool_hook_executor = tool_hook_executor

    def run_sync(self, flow: TurnFlow) -> TurnFlow:
        """执行同步推理，必要时使用流式首轮结果。"""

        if self.enable_thinking and self.event_bus:
            chat_id = getattr(flow, "chat_id", "") or flow.session_id
            if chat_id:
                self.event_bus.publish(
                    StreamDeltaReady(
                        trace_id=flow.trace_id,
                        session_id=flow.session_id,
                        delta="🤔 正在思考...",
                        channel=flow.channel,
                        chat_id=str(chat_id),
                    )
                )

                def on_delta(delta: str) -> None:
                    self._mark_first_token(flow, delta)
                    self.event_bus.publish(
                        StreamDeltaReady(
                            trace_id=flow.trace_id,
                            session_id=flow.session_id,
                            delta=delta,
                            channel=flow.channel,
                            chat_id=str(chat_id),
                        )
                    )

                if hasattr(self.agent.llm_client, "generate_stream"):
                    with llm_stage("passive"):
                        result = self.agent.llm_client.generate_stream(
                            messages=flow.messages,
                            tools=flow.tools,
                            on_delta=on_delta,
                        )
                    if getattr(result, "error", None):
                        return self._finish_llm_error(flow, result)
                    if getattr(result, "tool_calls", None):
                        self._mark_first_token(flow, getattr(result, "content", ""))
                        return self._run_tool_loop(flow, initial_result=result)
                    content = str(getattr(result, "content", "") or "")
                    self._mark_first_token(flow, content)
                    if content.strip():
                        flow.final_output = content
                        return flow
                    logger.warning("流式推理返回空内容，改用普通工具循环")

        return self._run_tool_loop(flow)

    async def run_async(self, flow: TurnFlow) -> TurnFlow:
        """通过异步模型接口执行推理与工具循环。"""

        return await self._run_tool_loop_async(flow)

    async def _run_tool_loop_async(self, flow: TurnFlow) -> TurnFlow:
        current_messages = list(flow.messages)
        loop_started = time.perf_counter()
        for step in range(self.max_tool_steps):
            with llm_stage("passive"):
                result = await self.agent.generate_from_messages_async(
                    current_messages,
                    tools=flow.tools if flow.tools else None,
                )
            self._mark_first_token(flow, result.content)
            if getattr(result, "error", None):
                return self._finish_llm_error(flow, result)
            if not result.tool_calls:
                flow.final_output = result.content or ""
                self._record_event(
                    {
                        "type": "tool_loop_perf",
                        "trace_id": flow.trace_id,
                        "session_id": flow.session_id,
                        "steps": step,
                        "latency_ms": round(
                            (time.perf_counter() - loop_started) * 1000,
                            2,
                        ),
                    }
                )
                return flow
            current_messages.append(self._assistant_message(result))
            for tool_call in result.tool_calls:
                tool_message = self._execute_tool(
                    tool_call,
                    flow,
                    step,
                    async_mode=True,
                )
                current_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_message,
                    }
                )
        return await self._finish_after_tool_limit_async(flow, current_messages)

    def _run_tool_loop(self, flow: TurnFlow, initial_result=None) -> TurnFlow:
        current_messages = list(flow.messages)
        loop_started = time.perf_counter()
        for step in range(self.max_tool_steps):
            if step == 0 and initial_result is not None:
                result = initial_result
            else:
                with llm_stage("passive"):
                    result = self.agent.generate_from_messages(
                        current_messages,
                        tools=flow.tools if flow.tools else None,
                    )
            self._mark_first_token(flow, result.content)
            if getattr(result, "error", None):
                return self._finish_llm_error(flow, result)
            if not result.tool_calls:
                flow.final_output = result.content or ""
                self._record_event(
                    {
                        "type": "tool_loop_perf",
                        "trace_id": flow.trace_id,
                        "session_id": flow.session_id,
                        "steps": step,
                        "latency_ms": round(
                            (time.perf_counter() - loop_started) * 1000, 2
                        ),
                    }
                )
                return flow
            current_messages.append(self._assistant_message(result))
            for tool_call in result.tool_calls:
                tool_message = self._execute_tool(tool_call, flow, step)
                current_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_message,
                    }
                )
        self._finish_after_tool_limit(flow, current_messages)
        self._record_event(
            {
                "type": "tool_loop_perf",
                "trace_id": flow.trace_id,
                "session_id": flow.session_id,
                "steps": self.max_tool_steps,
                "latency_ms": round((time.perf_counter() - loop_started) * 1000, 2),
            }
        )
        return flow

    async def _finish_after_tool_limit_async(
        self,
        flow: TurnFlow,
        current_messages: list[dict[str, Any]],
    ) -> TurnFlow:
        with llm_stage("passive"):
            result = await self.agent.generate_from_messages_async(
                self._tool_limit_messages(current_messages),
                tools=None,
            )
        if getattr(result, "error", None):
            self._finish_llm_error(flow, result)
            return
        flow.final_output = result.content or self._tool_limit_fallback(flow)
        return flow

    def _finish_after_tool_limit(
        self,
        flow: TurnFlow,
        current_messages: list[dict[str, Any]],
    ) -> None:
        with llm_stage("passive"):
            result = self.agent.generate_from_messages(
                self._tool_limit_messages(current_messages),
                tools=None,
            )
        if getattr(result, "error", None):
            self._finish_llm_error(flow, result)
            return
        flow.final_output = result.content or self._tool_limit_fallback(flow)

    def _finish_llm_error(self, flow: TurnFlow, result) -> TurnFlow:
        flow.final_output = result.content or "模型服务暂时不可用，请稍后重试。"
        flow.extensions["llm_error"] = result.error
        flow.extensions["llm_error_type"] = getattr(result, "error_type", "")
        flow.extensions["llm_status_code"] = getattr(result, "status_code", None)
        self._record_event(
            {
                "type": "llm_error",
                "trace_id": flow.trace_id,
                "session_id": flow.session_id,
                "stage": getattr(result, "stage", "passive"),
                "error_type": getattr(result, "error_type", ""),
                "status_code": getattr(result, "status_code", None),
            }
        )
        logger.error(
            "passive LLM request failed: trace=%s stage=%s error_type=%s status_code=%s",
            flow.trace_id,
            getattr(result, "stage", "passive"),
            getattr(result, "error_type", ""),
            getattr(result, "status_code", ""),
        )
        return flow

    @staticmethod
    def _tool_limit_messages(
        current_messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            *current_messages,
            {
                "role": "system",
                "content": (
                    "工具调用已达到本回合上限。不要再调用工具；请根据已有工具结果，"
                    "直接给用户一个简洁的最终答复。若任务尚未完成，说明已完成部分和下一步。"
                ),
            },
        ]

    def _tool_limit_fallback(self, flow: TurnFlow) -> str:
        return (
            f"本回合已完成 {len(flow.tool_trace)} 次工具调用。"
            "请基于当前结果继续，或将任务拆分为下一步。"
        )

    def _execute_tool(
        self,
        tool_call: LLMToolCall,
        flow: TurnFlow,
        step: int,
        *,
        async_mode: bool = False,
    ) -> str:
        tool_input = self._tool_input_for_flow(tool_call, flow)
        if self.tool_hook_executor is not None:
            outcome = self.tool_hook_executor.execute_sync(
                tool_call.name,
                tool_input,
                flow.session_id,
            )
            if outcome.decision == "deny":
                flow.tool_trace.append(
                    {
                        "step": str(step + 1),
                        "tool": tool_call.name,
                        "status": "blocked",
                        "arguments": tool_call.arguments_json,
                    }
                )
                tool_label = tool_call.name if async_mode else f"`{tool_call.name}`"
                return f"Tool {tool_label} ok=False: 插件钩子阻止执行: {outcome.reason}"
            if outcome.modified_args is not None:
                tool_input = dict(outcome.modified_args)

        tool_result = self.tool_registry.execute(
            tool_name=tool_call.name,
            tool_input=tool_input,
        )
        flow.tool_trace.append(
            {
                "step": str(step + 1),
                "tool": tool_call.name,
                "status": "ok" if tool_result.ok else "failed",
                "arguments": tool_call.arguments_json,
            }
        )
        tool_label = tool_call.name if async_mode else f"`{tool_call.name}`"
        return f"Tool {tool_label} ok={tool_result.ok}: {tool_result.content}"

    @staticmethod
    def _assistant_message(result) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": result.content or "",
            "tool_calls": [
                PassiveReasoner._tool_call_to_message_item(tool_call)
                for tool_call in result.tool_calls
            ],
        }

    @staticmethod
    def _tool_input_for_flow(
        tool_call: LLMToolCall,
        flow: TurnFlow,
    ) -> dict[str, Any]:
        tool_input = dict(tool_call.arguments)
        if tool_call.name in {
            "schedule_task",
            "list_scheduled_tasks",
            "cancel_scheduled_task",
            "configure_proactive_policy",
            "get_proactive_status",
            "spawn",
            "task",
        }:
            tool_input["__session_id"] = flow.session_id
            tool_input["__trace_id"] = flow.trace_id
            tool_input["__channel"] = flow.channel
            tool_input["__chat_id"] = getattr(flow, "chat_id", "") or flow.session_id
        if tool_call.name == "message_push":
            tool_input["channel"] = flow.channel
            tool_input["chat_id"] = getattr(flow, "chat_id", "") or flow.session_id
        return tool_input

    @staticmethod
    def _tool_call_to_message_item(tool_call: LLMToolCall) -> dict[str, Any]:
        return {
            "id": tool_call.id,
            "type": "function",
            "function": {
                "name": tool_call.name,
                "arguments": tool_call.arguments_json,
            },
        }

    def _record_event(self, event: dict[str, Any]) -> None:
        if self.recorder is not None:
            self.recorder.record(event)

    def _mark_first_token(self, flow: TurnFlow, content: str) -> None:
        """记录本轮首次出现可见模型内容的时间。"""

        if not str(content or "").strip():
            return
        if "first_token_latency_ms" in flow.extensions:
            return
        started = flow.extensions.get("_turn_started_at")
        if not isinstance(started, (int, float)):
            return
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        flow.extensions["first_token_latency_ms"] = latency_ms
        self._record_event(
            {
                "type": "turn_first_token",
                "trace_id": flow.trace_id,
                "session_id": flow.session_id,
                "latency_ms": latency_ms,
            }
        )

from dataclasses import dataclass
import logging
import time
from typing import Any
from uuid import uuid4

from flow_agent.core.agent import Agent
from flow_agent.core.context_store import ContextStore
from flow_agent.core.delegation import DelegationPolicy
from flow_agent.core.models import AgentResponse
from flow_agent.infra.logging import trace_id_var
from flow_agent.infra.trace import TraceRecorder
from flow_agent.llm.client import LLMToolCall
from flow_agent.memory.organizer import MemoryOrganizer
from flow_agent.memory.models import RetrievedMemory
from flow_agent.memory.retriever import MemoryRetriever
from flow_agent.tools.registry import ToolRegistry
from flow_agent.dashboard.store import InMemoryDashboardStore


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TurnState:
    user_input: str
    session_id: str
    trace_id: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    retrieval_trace: list[dict[str, str]]
    tool_trace: list[dict[str, str]]
    delegation_action: str = "handle_locally"
    channel: str = "cli"
    final_output: str = ""


class TurnPipeline:
    def __init__(
        self,
        agent: Agent,
        tool_registry: ToolRegistry,
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

    def process_turn(self, user_input: str, session_id: str) -> AgentResponse:
        state = self.prepare_context(user_input=user_input, session_id=session_id)
        token = trace_id_var.set(state.trace_id)
        turn_started = time.perf_counter()
        try:
            self._record_event(
                {
                    "type": "turn_start",
                    "trace_id": state.trace_id,
                    "session_id": state.session_id,
                    "user_input": state.user_input,
                }
            )
            logger.info("turn start session=%s", state.session_id)
            state = self._run_phase(state, "prepare", self.context_prepare)
            state = self._run_phase(state, "reason", self.reasoner_run_turn)
            self._run_phase(state, "commit", self._commit_phase)
            self._record_event(
                {
                    "type": "turn_end",
                    "trace_id": state.trace_id,
                    "session_id": state.session_id,
                    "assistant_output": state.final_output,
                    "retrieval_trace": state.retrieval_trace,
                    "tool_trace": state.tool_trace,
                }
            )
            logger.info("turn end session=%s", state.session_id)
            self._record_event(
                {
                    "type": "turn_perf",
                    "trace_id": state.trace_id,
                    "session_id": state.session_id,
                    "latency_ms": round((time.perf_counter() - turn_started) * 1000, 2),
                }
            )
            return AgentResponse(content=state.final_output)
        except Exception as exc:
            self._record_event(
                {
                    "type": "turn_error",
                    "trace_id": state.trace_id,
                    "session_id": state.session_id,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "failure_stage": "process_turn",
                }
            )
            logger.exception("turn error session=%s", state.session_id)
            raise
        finally:
            trace_id_var.reset(token)

    def prepare_context(self, user_input: str, session_id: str) -> TurnState:
        self.agent.set_session(session_id)
        return TurnState(
            user_input=user_input,
            session_id=session_id,
            trace_id=uuid4().hex[:12],
            messages=[],
            tools=[],
            retrieval_trace=[],
            tool_trace=[],
        )

    def context_prepare(self, state: TurnState) -> TurnState:
        proactive_mode = state.channel == "proactive"
        persona_block = ""
        if self.agent.persona_resolver is not None:
            persona_block = self.agent.persona_resolver.render_block(
                channel=state.channel,
                proactive_mode=proactive_mode,
            )
        retrieval_started = time.perf_counter()
        bundle = self.context_store.prepare(
            session_id=state.session_id,
            user_input=state.user_input,
            channel_metadata={"channel": state.channel},
            persona_block=persona_block,
        )
        state.retrieval_trace = bundle.retrieval_trace
        self._record_event(
            {
                "type": "retrieval",
                "trace_id": state.trace_id,
                "session_id": state.session_id,
                "items": len(bundle.retrieved),
                "hit": bool(bundle.retrieved),
                "latency_ms": round((time.perf_counter() - retrieval_started) * 1000, 2),
            }
        )
        memory_block = self._render_memory_block(bundle.retrieved)
        retrieval_block = self._render_retrieval_block(bundle.retrieved)
        runtime_block = f"channel={state.channel}; session={state.session_id}"
        state.messages = self.agent.build_turn_messages(
            user_input=state.user_input,
            persona_block=persona_block,
            memory_block=memory_block,
            retrieval_block=retrieval_block,
            runtime_block=runtime_block,
        )
        state.tools = self.tool_registry.select_openai_tools(
            state.user_input,
            max_tools=self.tool_selection_max,
        )
        self._record_event(
            {
                "type": "tool_selection",
                "trace_id": state.trace_id,
                "session_id": state.session_id,
                "selected": len(state.tools),
                "available": len(self.tool_registry.list_openai_tools()),
            }
        )
        return state

    # Backward-compatible alias used by existing tests/code.
    def build_prompt(self, state: TurnState) -> TurnState:
        return self.context_prepare(state)

    def _render_memory_block(self, retrieved: list[RetrievedMemory]) -> str:
        if not retrieved:
            return ""
        memory_lines = [f"- ({m.role}, score={m.score:.2f}) {m.content}" for m in retrieved]
        return "Relevant memory:\n" + "\n".join(memory_lines)

    def _render_retrieval_block(self, retrieved: list[RetrievedMemory]) -> str:
        if not retrieved:
            return ""
        retrieval_lines = [f"- {m.content[:120]}" for m in retrieved]
        return "Retrieval results:\n" + "\n".join(retrieval_lines)

    def reasoner_run_turn(self, state: TurnState) -> TurnState:
        decision = self.delegation_policy.decide(
            user_input=state.user_input,
            tool_step_budget=self.max_tool_steps,
        )
        state.delegation_action = decision.action
        self._record_event(
            {
                "type": "delegation_decision",
                "trace_id": state.trace_id,
                "session_id": state.session_id,
                "action": decision.action,
                "reason": decision.reason,
            }
        )
        if decision.action == "reject":
            state.final_output = "请求被策略拒绝，请调整后重试。"
            return state
        if decision.action == "background_job":
            state.final_output = "任务已转为后台执行。"
            return state
        if decision.action == "spawn_subagent":
            state.final_output = "任务已委派给子代理执行。"
            return state

        return self.run_llm_tool_loop(state)

    def run_llm_tool_loop(self, state: TurnState) -> TurnState:
        current_messages: list[dict[str, Any]] = list(state.messages)
        seen_calls: set[str] = set()
        loop_started = time.perf_counter()

        for step in range(self.max_tool_steps):
            llm_result = self.agent.generate_from_messages(current_messages, tools=state.tools)
            if not llm_result.tool_calls:
                state.final_output = llm_result.content
                self._record_event(
                    {
                        "type": "tool_loop_perf",
                        "trace_id": state.trace_id,
                        "session_id": state.session_id,
                        "steps": step + 1,
                        "latency_ms": round((time.perf_counter() - loop_started) * 1000, 2),
                    }
                )
                return state

            self._record_event(
                {
                    "type": "tool_call",
                    "trace_id": state.trace_id,
                    "session_id": state.session_id,
                    "step": step + 1,
                    "count": len(llm_result.tool_calls),
                }
            )

            current_messages.append(
                {
                    "role": "assistant",
                    "content": llm_result.content or "",
                    "tool_calls": [
                        self._tool_call_to_message_item(tool_call)
                        for tool_call in llm_result.tool_calls
                    ],
                }
            )

            for tool_call in llm_result.tool_calls:
                signature = f"{tool_call.name}:{tool_call.arguments_json}"
                if signature in seen_calls:
                    tool_message = (
                        f"Tool `{tool_call.name}` blocked due to repeated call pattern."
                    )
                    state.tool_trace.append(
                        {
                            "step": str(step + 1),
                            "tool": tool_call.name,
                            "status": "blocked_repeat",
                        }
                    )
                else:
                    seen_calls.add(signature)
                    tool_result, metadata = self.tool_registry.execute_with_policy(
                        tool_name=tool_call.name,
                        tool_input=tool_call.arguments,
                    )
                    tool_message = f"Tool `{tool_call.name}` ok={tool_result.ok}: {tool_result.content}"
                    state.tool_trace.append(
                        {
                            "step": str(step + 1),
                            "tool": tool_call.name,
                            "status": "ok" if tool_result.ok else "failed",
                            "risk": str(metadata.get("risk", "read-only")),
                            "attempts": str(metadata.get("attempts", 1)),
                        }
                    )

                self._record_event(
                    {
                        "type": "tool_result",
                        "trace_id": state.trace_id,
                        "session_id": state.session_id,
                        "step": step + 1,
                        "tool": tool_call.name,
                        "status": state.tool_trace[-1]["status"],
                        "risk": state.tool_trace[-1].get("risk", "read-only"),
                        "attempts": int(state.tool_trace[-1].get("attempts", "1")),
                    }
                )

                current_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_message,
                    }
                )

        state.final_output = "工具调用次数超过上限，请调整请求后重试。"
        self._record_event(
            {
                "type": "tool_loop_perf",
                "trace_id": state.trace_id,
                "session_id": state.session_id,
                "steps": self.max_tool_steps,
                "latency_ms": round((time.perf_counter() - loop_started) * 1000, 2),
            }
        )
        return state

    def _record_event(self, event: dict[str, Any]) -> None:
        if self.dashboard is not None:
            try:
                self.dashboard.record(event)
            except Exception:
                logger.exception("dashboard record failed")
        if self.recorder is None:
            return
        self.recorder.record(event)

    def _run_phase(self, state: TurnState, phase: str, fn):
        started = time.perf_counter()
        self._record_event(
            {
                "type": "turn_phase_start",
                "phase": phase,
                "trace_id": state.trace_id,
                "session_id": state.session_id,
                "status": "start",
            }
        )
        try:
            result = fn(state)
            self._record_event(
                {
                    "type": "turn_phase_end",
                    "phase": phase,
                    "trace_id": state.trace_id,
                    "session_id": state.session_id,
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
                    "trace_id": state.trace_id,
                    "session_id": state.session_id,
                    "status": "error",
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "failure_stage": phase,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            )
            raise

    def _commit_phase(self, state: TurnState) -> TurnState:
        self.context_commit(state)
        return state

    def context_commit(self, state: TurnState) -> None:
        self.context_store.commit(
            user_input=state.user_input,
            assistant_output=state.final_output,
        )
        if self.organizer is not None:
            stats = self.organizer.organize(state.session_id)
            self._record_event(
                {
                    "type": "memory_organize",
                    "trace_id": state.trace_id,
                    "session_id": state.session_id,
                    **stats,
                }
            )

    # Backward-compatible alias used by existing tests/code.
    def commit_result(self, state: TurnState) -> None:
        self.context_commit(state)

    def _tool_call_to_message_item(self, tool_call: LLMToolCall) -> dict[str, Any]:
        return {
            "id": tool_call.id,
            "type": "function",
            "function": {
                "name": tool_call.name,
                "arguments": tool_call.arguments_json,
            },
        }

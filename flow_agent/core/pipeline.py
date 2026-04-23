from dataclasses import dataclass
import logging
from typing import Any
from uuid import uuid4

from flow_agent.core.agent import Agent
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
    ) -> None:
        self.agent = agent
        self.tool_registry = tool_registry
        self.retriever = retriever
        self.retrieval_max_items = retrieval_max_items
        self.max_tool_steps = max_tool_steps
        self.recorder = recorder
        self.organizer = organizer
        self.dashboard = dashboard

    def process_turn(self, user_input: str, session_id: str) -> AgentResponse:
        state = self.prepare_context(user_input=user_input, session_id=session_id)
        token = trace_id_var.set(state.trace_id)
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
            state = self.build_prompt(state)
            state = self.run_llm_tool_loop(state)
            self.commit_result(state)
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
            return AgentResponse(content=state.final_output)
        except Exception as exc:
            self._record_event(
                {
                    "type": "turn_error",
                    "trace_id": state.trace_id,
                    "session_id": state.session_id,
                    "error": str(exc),
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

    def build_prompt(self, state: TurnState) -> TurnState:
        state.messages = self.agent.build_turn_messages(user_input=state.user_input)
        state.tools = self.tool_registry.list_openai_tools()
        if self.retriever is not None and self.retrieval_max_items > 0:
            retrieved = self.retriever.retrieve(
                session_id=state.session_id,
                query=state.user_input,
                max_items=self.retrieval_max_items,
            )
            state.retrieval_trace.append(
                {"items": str(len(retrieved)), "max_items": str(self.retrieval_max_items)}
            )
            self._record_event(
                {
                    "type": "retrieval",
                    "trace_id": state.trace_id,
                    "session_id": state.session_id,
                    "items": len(retrieved),
                }
            )
            if retrieved:
                state.messages = self._inject_memory_block(state.messages, retrieved)
        return state

    def _inject_memory_block(
        self,
        messages: list[dict[str, Any]],
        retrieved: list[RetrievedMemory],
    ) -> list[dict[str, Any]]:
        memory_lines = [
            f"- ({m.role}, score={m.score:.2f}) {m.content}" for m in retrieved
        ]
        memory_block = "Relevant memory:\n" + "\n".join(memory_lines)

        if not messages:
            return [{"role": "system", "content": memory_block}]
        if messages[0].get("role") != "system":
            return [{"role": "system", "content": memory_block}] + list(messages)
        return [messages[0], {"role": "system", "content": memory_block}] + messages[1:]

    def run_llm_tool_loop(self, state: TurnState) -> TurnState:
        current_messages: list[dict[str, Any]] = list(state.messages)
        seen_calls: set[str] = set()

        for step in range(self.max_tool_steps):
            llm_result = self.agent.generate_from_messages(current_messages, tools=state.tools)
            if not llm_result.tool_calls:
                state.final_output = llm_result.content
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
                    try:
                        tool_result = self.tool_registry.execute(
                            tool_name=tool_call.name,
                            tool_input=tool_call.arguments,
                        )
                        tool_message = (
                            f"Tool `{tool_call.name}` ok={tool_result.ok}: {tool_result.content}"
                        )
                        state.tool_trace.append(
                            {
                                "step": str(step + 1),
                                "tool": tool_call.name,
                                "status": "ok" if tool_result.ok else "failed",
                            }
                        )
                    except Exception as exc:
                        tool_message = f"Tool `{tool_call.name}` failed with exception: {exc}"
                        state.tool_trace.append(
                            {
                                "step": str(step + 1),
                                "tool": tool_call.name,
                                "status": "exception",
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

    def commit_result(self, state: TurnState) -> None:
        self.agent.commit_turn(
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

    def _tool_call_to_message_item(self, tool_call: LLMToolCall) -> dict[str, Any]:
        return {
            "id": tool_call.id,
            "type": "function",
            "function": {
                "name": tool_call.name,
                "arguments": tool_call.arguments_json,
            },
        }

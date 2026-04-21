from dataclasses import dataclass
from typing import Any

from flow_agent.core.agent import Agent
from flow_agent.core.models import AgentResponse
from flow_agent.llm.client import LLMToolCall
from flow_agent.tools.registry import ToolRegistry


@dataclass(slots=True)
class TurnState:
    user_input: str
    session_id: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    tool_trace: list[dict[str, str]]
    final_output: str = ""


class TurnPipeline:
    def __init__(
        self,
        agent: Agent,
        tool_registry: ToolRegistry,
        max_tool_steps: int = 5,
    ) -> None:
        self.agent = agent
        self.tool_registry = tool_registry
        self.max_tool_steps = max_tool_steps

    def process_turn(self, user_input: str, session_id: str) -> AgentResponse:
        state = self.prepare_context(user_input=user_input, session_id=session_id)
        state = self.build_prompt(state)
        state = self.run_llm_tool_loop(state)
        self.commit_result(state)
        return AgentResponse(content=state.final_output)

    def prepare_context(self, user_input: str, session_id: str) -> TurnState:
        self.agent.set_session(session_id)
        return TurnState(
            user_input=user_input,
            session_id=session_id,
            messages=[],
            tools=[],
            tool_trace=[],
        )

    def build_prompt(self, state: TurnState) -> TurnState:
        state.messages = self.agent.build_turn_messages(user_input=state.user_input)
        state.tools = self.tool_registry.list_openai_tools()
        return state

    def run_llm_tool_loop(self, state: TurnState) -> TurnState:
        current_messages: list[dict[str, Any]] = list(state.messages)
        seen_calls: set[str] = set()

        for step in range(self.max_tool_steps):
            llm_result = self.agent.generate_from_messages(current_messages, tools=state.tools)
            if not llm_result.tool_calls:
                state.final_output = llm_result.content
                return state

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

                current_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_message,
                    }
                )

        state.final_output = "工具调用次数超过上限，请调整请求后重试。"
        return state

    def commit_result(self, state: TurnState) -> None:
        self.agent.commit_turn(
            user_input=state.user_input,
            assistant_output=state.final_output,
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

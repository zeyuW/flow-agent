from typing import Any

from flow_agent.core.agent import Agent
from flow_agent.core.models import AgentResponse
from flow_agent.llm.client import LLMToolCall
from flow_agent.tools.registry import ToolRegistry


class Orchestrator:
    def __init__(self, agent: Agent, tool_registry: ToolRegistry) -> None:
        self.agent = agent
        self.tool_registry = tool_registry

    def run_turn(self, user_input: str, session_id: str = "default") -> AgentResponse:
        self.agent.set_session(session_id)
        messages = self.agent.build_turn_messages(user_input=user_input)
        tools = self.tool_registry.list_openai_tools()
        first_pass = self.agent.generate_from_messages(messages, tools=tools)

        if not first_pass.tool_calls:
            self.agent.commit_turn(user_input=user_input, assistant_output=first_pass.content)
            return AgentResponse(content=first_pass.content)

        second_pass_messages: list[dict[str, Any]] = list(messages)
        second_pass_messages.append(
            {
                "role": "assistant",
                "content": first_pass.content or "",
                "tool_calls": [self._tool_call_to_message_item(tc) for tc in first_pass.tool_calls],
            }
        )

        for tool_call in first_pass.tool_calls:
            tool_result = self.tool_registry.execute(
                tool_name=tool_call.name,
                tool_input=tool_call.arguments,
            )
            second_pass_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": (
                        f"Tool `{tool_call.name}` ok={tool_result.ok}: {tool_result.content}"
                    ),
                }
            )

        final_reply = self.agent.generate_from_messages(second_pass_messages, tools=tools)
        self.agent.commit_turn(
            user_input=user_input,
            assistant_output=final_reply.content,
        )
        return AgentResponse(content=final_reply.content)

    def _tool_call_to_message_item(self, tool_call: LLMToolCall) -> dict[str, Any]:
        return {
            "id": tool_call.id,
            "type": "function",
            "function": {
                "name": tool_call.name,
                "arguments": tool_call.arguments_json,
            },
        }

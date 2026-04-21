from typing import Any

from flow_agent.config.settings import Settings
from flow_agent.core.context import ConversationContext
from flow_agent.core.models import AgentResponse
from flow_agent.llm.client import LLMClient
from flow_agent.llm.prompts import build_messages


class Agent:
    def __init__(
        self,
        settings: Settings,
        llm_client: LLMClient,
        context: ConversationContext,
        session_id: str = "default",
    ) -> None:
        self.settings = settings
        self.llm_client = llm_client
        self.context = context
        self.session_id = session_id

    def set_session(self, session_id: str) -> None:
        self.session_id = session_id

    def run(self, user_input: str) -> AgentResponse:
        messages = self.build_turn_messages(user_input=user_input)
        result = self.llm_client.generate(messages)

        self.context.append_user_message(self.session_id, user_input)
        self.context.append_assistant_message(self.session_id, result.content)

        return AgentResponse(content=result.content)

    def build_turn_messages(
        self,
        user_input: str,
    ) -> list[dict[str, str]]:
        return build_messages(
            system_prompt=self.settings.system_prompt,
            user_input=user_input,
            history=self.context.get_history(self.session_id),
        )

    def generate_from_messages(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ):
        return self.llm_client.generate(messages, tools=tools)

    def commit_turn(self, user_input: str, assistant_output: str) -> None:
        self.context.append_user_message(self.session_id, user_input)
        self.context.append_assistant_message(self.session_id, assistant_output)

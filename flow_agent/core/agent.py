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
    ) -> None:
        self.settings = settings
        self.llm_client = llm_client
        self.context = context

    def run(self, user_input: str) -> AgentResponse:
        messages = build_messages(
            system_prompt=self.settings.system_prompt,
            user_input=user_input,
            history=self.context.get_history(),
        )

        result = self.llm_client.generate(messages)

        self.context.append_user_message(user_input)
        self.context.append_assistant_message(result.content)

        return AgentResponse(content=result.content)

from flow_agent.config.loader import load_settings
from flow_agent.core.agent import Agent
from flow_agent.core.context import ConversationContext
from flow_agent.llm.client import OpenAILLMClient


def create_agent() -> Agent:
    settings = load_settings()
    context = ConversationContext()
    # llm_client = FakeLLMClient()
    llm_client = OpenAILLMClient(settings)

    return Agent(
        settings=settings,
        llm_client=llm_client,
        context=context,
    )

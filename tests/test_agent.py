from flow_agent.config.settings import Settings
from flow_agent.core.agent import Agent
from flow_agent.core.context import ConversationContext
from flow_agent.llm.client import FakeLLMClient
from flow_agent.llm.prompts import build_messages


def test_build_messages():
    messages = build_messages(
        system_prompt="system",
        user_input="hello",
        history=[{"role": "assistant", "content": "hi"}],
    )

    assert messages == [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "hello"},
    ]


def test_fake_llm_client():
    client = FakeLLMClient()
    result = client.generate([{"role": "user", "content": "hello"}])

    assert result.content == "echo: hello"


def test_agent_run():
    settings = Settings(
        model="fake-model",
        api_key="fake-key",
        system_prompt="You are helpful.",
    )
    context = ConversationContext()
    client = FakeLLMClient()
    agent = Agent(settings=settings, llm_client=client, context=context)

    response = agent.run("hello")

    assert response.content == "echo: hello"
    assert context.get_history() == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "echo: hello"},
    ]

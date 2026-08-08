from application.conversation.app.agent import Agent
from application.conversation.infra.context import ConversationContext
from application.capabilities.llm.client import FakeLLMClient, OpenAILLMClient
from application.capabilities.llm.prompts import build_messages
from infra.config.schema import ModelEndpointConfig


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


def test_openai_client_uses_one_explicit_endpoint(monkeypatch):
    created: list[tuple[str, str | None]] = []

    def create_client(*, api_key: str, base_url: str | None):
        created.append((api_key, base_url))
        return object()

    monkeypatch.setattr("application.capabilities.llm.client.OpenAI", create_client)
    monkeypatch.setattr("application.capabilities.llm.client.AsyncOpenAI", create_client)
    endpoint = ModelEndpointConfig(
        model="model-name",
        api_key="secret",
        base_url="https://example.test/v1",
    )

    client = OpenAILLMClient(endpoint)

    assert client.model == "model-name"
    assert created == [
        ("secret", "https://example.test/v1"),
        ("secret", "https://example.test/v1"),
    ]


def test_agent_run():
    context = ConversationContext()
    client = FakeLLMClient()
    agent = Agent(
        system_prompt="You are helpful.",
        llm_client=client,
        context=context,
    )

    response = agent.run("hello")

    assert response.content == "echo: hello"
    assert context.get_history("default") == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "echo: hello"},
    ]


def test_context_uses_session_storage(tmp_path):
    context = ConversationContext(db_path=tmp_path / "sessions.db")

    context.append_user_message("s1", "u1")
    context.append_assistant_message("s1", "a1")

    assert context.get_history("s1") == [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
    ]

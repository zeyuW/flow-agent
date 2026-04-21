from flow_agent.config.settings import (
    LoggingSettings,
    ModelSettings,
    SessionSettings,
    Settings,
    StorageSettings,
    ToolingSettings,
)
from flow_agent.core.agent import Agent
from flow_agent.core.context import ConversationContext
from flow_agent.llm.client import FakeLLMClient
from flow_agent.llm.prompts import build_messages
from flow_agent.memory.store import InMemoryMessageStore


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
        model=ModelSettings(
            model_id="fake-model",
            api_key="fake-key",
            base_url=None,
            system_prompt="You are helpful.",
        ),
        storage=StorageSettings(memory_db_path="/tmp/memory.db"),
        logging=LoggingSettings(level="INFO"),
        session=SessionSettings(default_session_id="default"),
        tooling=ToolingSettings(enabled=True),
    )
    context = ConversationContext()
    client = FakeLLMClient()
    agent = Agent(settings=settings, llm_client=client, context=context)

    response = agent.run("hello")

    assert response.content == "echo: hello"
    assert context.get_history("default") == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "echo: hello"},
    ]


def test_context_uses_store():
    store = InMemoryMessageStore()
    context = ConversationContext(store=store)

    context.append_user_message("s1", "u1")
    context.append_assistant_message("s1", "a1")

    assert store.list_messages("s1") == [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
    ]
    assert context.get_history("s1") == store.list_messages("s1")

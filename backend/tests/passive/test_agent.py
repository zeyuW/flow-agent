from application.agent.app.agent import Agent
from application.capabilities.tools.registry import ToolRegistry
from application.passive.infra.session_manager import ConversationContext
from application.passive.app.phase import TurnFlow
from application.passive.app.prompt import PromptRenderer
from application.capabilities.llm.client import FakeLLMClient, OpenAILLMClient
from application.capabilities.llm.prompts import build_messages
from infra.config import ModelEndpointConfig


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
    monkeypatch.setattr(
        "application.capabilities.llm.client.AsyncOpenAI", create_client
    )
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


def test_prompt_renderer_requires_selected_core_tool_use():
    context = ConversationContext()
    agent = Agent(
        system_prompt="You are helpful.",
        llm_client=FakeLLMClient(),
        context=context,
    )
    registry = ToolRegistry()
    registry.register(EchoTool())
    renderer = PromptRenderer(agent=agent, tool_registry=registry)

    flow = renderer.render(
        TurnFlow(
            user_input="请写入一个文件",
            session_id="session",
            channel="telegram",
            trace_id="trace",
        )
    )

    assert [item["function"]["name"] for item in flow.tools] == ["write"]
    system_content = "\n".join(
        str(message["content"])
        for message in flow.messages
        if message["role"] == "system"
    )
    assert "不得声称没有该能力" in system_content


def test_prompt_renderer_requires_flow_skill_installer():
    context = ConversationContext()
    agent = Agent(
        system_prompt="You are helpful.",
        llm_client=FakeLLMClient(),
        context=context,
    )
    registry = ToolRegistry()
    registry.register(InstallSkillTool())
    renderer = PromptRenderer(agent=agent, tool_registry=registry)

    flow = renderer.render(
        TurnFlow(
            user_input="请安装这个 Skill 仓库 https://github.com/Leonxlnx/taste-skill",
            session_id="session",
            channel="telegram",
            trace_id="trace",
        )
    )

    assert [item["function"]["name"] for item in flow.tools] == ["install_skill"]
    system_content = "\n".join(
        str(message["content"])
        for message in flow.messages
        if message["role"] == "system"
    )
    assert "不得使用 npx skills" in system_content


class EchoTool:
    @property
    def name(self) -> str:
        return "write"

    @property
    def description(self) -> str:
        return "写入文件"

    @property
    def input_schema(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}


class InstallSkillTool(EchoTool):
    @property
    def name(self) -> str:
        return "install_skill"


def test_context_uses_session_storage(tmp_path):
    context = ConversationContext(db_path=tmp_path / "sessions.db")

    context.append_user_message("s1", "u1")
    context.append_assistant_message("s1", "a1")

    assert context.get_history("s1") == [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
    ]

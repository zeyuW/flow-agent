from flow_agent.config.settings import (
    LoggingSettings,
    MemoryPolicySettings,
    ModelSettings,
    ObserveSettings,
    ProactiveSettings,
    RetrievalSettings,
    SessionSettings,
    Settings,
    StorageSettings,
    ToolingSettings,
)
from flow_agent.core.agent import Agent
from flow_agent.core.context import ConversationContext
from flow_agent.core.orchestrator import Orchestrator
from flow_agent.llm.client import LLMResult, LLMToolCall
from flow_agent.tools.base import ToolResult
from flow_agent.tools.registry import ToolRegistry

# 工具调用闭环测试
class ScriptedLLMClient:
    def __init__(self) -> None:
        self.calls = 0
        self.last_messages: list[dict[str, object]] = []

    def generate(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
    ) -> LLMResult:
        self.calls += 1
        self.last_messages = messages
        if self.calls == 1:
            return LLMResult(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call_1",
                        name="fake_tool",
                        arguments_json='{"query":"hello"}',
                        arguments={"query": "hello"},
                    )
                ],
            )
        return LLMResult(content="final answer from tool")


class FakeTool:
    @property
    def name(self) -> str:
        return "fake_tool"

    @property
    def description(self) -> str:
        return "Return fake result"

    @property
    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }

    def run(self, tool_input: dict[str, str]) -> ToolResult:
        return ToolResult(ok=True, content=f"tool got: {tool_input.get('query', '')}")


def test_orchestrator_tool_call_loop():
    settings = Settings(
        model=ModelSettings(
            model="fake-model",
            api_key="fake-key",
            base_url=None,
            system_prompt="You are helpful.",
        ),
        storage=StorageSettings(memory_db_path="/tmp/memory.db"),
        logging=LoggingSettings(level="INFO"),
        session=SessionSettings(default_session_id="default"),
        tooling=ToolingSettings(enabled=True),
        retrieval=RetrievalSettings(enabled=True),
        observe=ObserveSettings(enabled=False),
        memory_policy=MemoryPolicySettings(enabled=False),
        proactive=ProactiveSettings(enabled=False),
    )
    context = ConversationContext()
    llm_client = ScriptedLLMClient()
    agent = Agent(settings=settings, llm_client=llm_client, context=context)
    registry = ToolRegistry()
    registry.register(FakeTool())
    orchestrator = Orchestrator(agent=agent, tool_registry=registry)

    response = orchestrator.run_turn("please use tool", session_id="s1")

    assert response.content == "final answer from tool"
    assert llm_client.calls == 2
    tool_messages = [msg for msg in llm_client.last_messages if msg["role"] == "tool"]
    assert tool_messages
    assert tool_messages[0]["tool_call_id"] == "call_1"
    assert context.get_history("s1") == [
        {"role": "user", "content": "please use tool"},
        {"role": "assistant", "content": "final answer from tool"},
    ]


def test_orchestrator_switches_sessions():
    settings = Settings(
        model=ModelSettings(
            model="fake-model",
            api_key="fake-key",
            base_url=None,
            system_prompt="You are helpful.",
        ),
        storage=StorageSettings(memory_db_path="/tmp/memory.db"),
        logging=LoggingSettings(level="INFO"),
        session=SessionSettings(default_session_id="default"),
        tooling=ToolingSettings(enabled=True),
        retrieval=RetrievalSettings(enabled=True),
        observe=ObserveSettings(enabled=False),
        memory_policy=MemoryPolicySettings(enabled=False),
        proactive=ProactiveSettings(enabled=False),
    )
    context = ConversationContext()
    llm_client = ScriptedLLMClient()
    agent = Agent(settings=settings, llm_client=llm_client, context=context)
    registry = ToolRegistry()
    registry.register(FakeTool())
    orchestrator = Orchestrator(agent=agent, tool_registry=registry)

    orchestrator.run_turn("msg a", session_id="a")
    orchestrator.run_turn("msg b", session_id="b")

    assert context.get_history("a") == [
        {"role": "user", "content": "msg a"},
        {"role": "assistant", "content": "final answer from tool"},
    ]
    assert context.get_history("b") == [
        {"role": "user", "content": "msg b"},
        {"role": "assistant", "content": "final answer from tool"},
    ]


class LoopingLLMClient:
    def __init__(self) -> None:
        self.calls = 0

    def generate(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
    ) -> LLMResult:
        self.calls += 1
        return LLMResult(
            content="",
            tool_calls=[
                LLMToolCall(
                    id=f"loop_{self.calls}",
                    name="fake_tool",
                    arguments_json='{"query":"same"}',
                    arguments={"query": "same"},
                )
            ],
        )


def test_orchestrator_tool_loop_respects_max_steps():
    settings = Settings(
        model=ModelSettings(
            model="fake-model",
            api_key="fake-key",
            base_url=None,
            system_prompt="You are helpful.",
        ),
        storage=StorageSettings(memory_db_path="/tmp/memory.db"),
        logging=LoggingSettings(level="INFO"),
        session=SessionSettings(default_session_id="default"),
        tooling=ToolingSettings(enabled=True, max_tool_steps=2),
        retrieval=RetrievalSettings(enabled=True),
        observe=ObserveSettings(enabled=False),
        memory_policy=MemoryPolicySettings(enabled=False),
        proactive=ProactiveSettings(enabled=False),
    )
    context = ConversationContext()
    llm_client = LoopingLLMClient()
    agent = Agent(settings=settings, llm_client=llm_client, context=context)
    registry = ToolRegistry()
    registry.register(FakeTool())
    orchestrator = Orchestrator(agent=agent, tool_registry=registry, max_tool_steps=2)

    response = orchestrator.run_turn("loop please", session_id="s-loop")

    assert response.content == "工具调用次数超过上限，请调整请求后重试。"
    assert context.get_history("s-loop")[-1]["content"] == response.content


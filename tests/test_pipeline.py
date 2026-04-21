from flow_agent.config.settings import (
    LoggingSettings,
    ModelSettings,
    ObserveSettings,
    RetrievalSettings,
    SessionSettings,
    Settings,
    StorageSettings,
    ToolingSettings,
)
from flow_agent.core.agent import Agent
from flow_agent.core.context import ConversationContext
from flow_agent.core.pipeline import TurnPipeline
from flow_agent.llm.client import LLMResult, LLMToolCall
from flow_agent.memory.retriever import KeywordMemoryRetriever
from flow_agent.memory.store import InMemoryMessageStore
from flow_agent.tools.base import ToolResult
from flow_agent.tools.registry import ToolRegistry


class ScriptedLLMClient:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return LLMResult(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call_p1",
                        name="fake_tool",
                        arguments_json='{"query":"pipeline"}',
                        arguments={"query": "pipeline"},
                    )
                ],
            )
        return LLMResult(content="pipeline final answer")


class FakeTool:
    @property
    def name(self) -> str:
        return "fake_tool"

    @property
    def description(self) -> str:
        return "fake tool"

    @property
    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }

    def run(self, tool_input: dict[str, str]) -> ToolResult:
        return ToolResult(ok=True, content=f"ok:{tool_input.get('query', '')}")


def _build_settings() -> Settings:
    return Settings(
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
        retrieval=RetrievalSettings(enabled=True),
        observe=ObserveSettings(enabled=False),
    )


def test_pipeline_process_turn():
    agent = Agent(
        settings=_build_settings(),
        llm_client=ScriptedLLMClient(),
        context=ConversationContext(),
    )
    registry = ToolRegistry()
    registry.register(FakeTool())
    pipeline = TurnPipeline(agent=agent, tool_registry=registry)

    response = pipeline.process_turn("run pipeline", session_id="pipe")

    assert response.content == "pipeline final answer"
    assert agent.context.get_history("pipe") == [
        {"role": "user", "content": "run pipeline"},
        {"role": "assistant", "content": "pipeline final answer"},
    ]


def test_pipeline_injects_memory_block():
    store = InMemoryMessageStore()
    store.append_message("s1", "user", "我叫小明")
    context = ConversationContext(store=store)
    agent = Agent(
        settings=_build_settings(),
        llm_client=ScriptedLLMClient(),
        context=context,
    )
    registry = ToolRegistry()
    registry.register(FakeTool())
    retriever = KeywordMemoryRetriever(store=store)
    pipeline = TurnPipeline(agent=agent, tool_registry=registry, retriever=retriever, retrieval_max_items=3)

    pipeline.prepare_context(user_input="我叫什么", session_id="s1")
    state = pipeline.build_prompt(pipeline.prepare_context(user_input="我叫什么", session_id="s1"))

    system_messages = [m for m in state.messages if m.get("role") == "system"]
    assert len(system_messages) >= 2
    assert "Relevant memory" in system_messages[1]["content"]

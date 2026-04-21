import json
from pathlib import Path

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
from flow_agent.core.orchestrator import Orchestrator
from flow_agent.infra.trace import TraceRecorder
from flow_agent.llm.client import LLMResult
from flow_agent.memory.store import InMemoryMessageStore
from flow_agent.tools.registry import ToolRegistry


class PlainLLMClient:
    def generate(self, messages, tools=None):
        return LLMResult(content="ok")


def test_trace_jsonl_written(tmp_path: Path):
    trace_path = tmp_path / "trace.jsonl"
    settings = Settings(
        model=ModelSettings(
            model_id="fake-model",
            api_key="fake-key",
            base_url=None,
            system_prompt="You are helpful.",
        ),
        storage=StorageSettings(memory_db_path=str(tmp_path / "memory.db")),
        logging=LoggingSettings(level="INFO"),
        session=SessionSettings(default_session_id="default"),
        tooling=ToolingSettings(enabled=False),
        retrieval=RetrievalSettings(enabled=False),
        observe=ObserveSettings(enabled=True, trace_path=str(trace_path)),
    )
    store = InMemoryMessageStore()
    context = ConversationContext(store=store)
    agent = Agent(settings=settings, llm_client=PlainLLMClient(), context=context)
    recorder = TraceRecorder(path=trace_path)
    orchestrator = Orchestrator(
        agent=agent,
        tool_registry=ToolRegistry(),
        recorder=recorder,
    )

    orchestrator.run_turn("hello", session_id="s1")

    lines = trace_path.read_text(encoding="utf-8").strip().splitlines()
    assert lines
    events = [json.loads(line) for line in lines]
    types = {e["type"] for e in events}
    assert "turn_start" in types
    assert "turn_end" in types

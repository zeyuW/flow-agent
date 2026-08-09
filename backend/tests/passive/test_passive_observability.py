"""被动 Telegram 主链路的调用次数和延迟观测契约。"""

import asyncio
import json
from types import SimpleNamespace

from application.agent.app.agent import Agent
from application.capabilities.llm.client import LLMResult, LLMToolCall
from application.agent.app.loop import AgentLoop
from application.passive.app.pipeline import PassiveTurnPipeline
from application.passive.infra.session_manager import ConversationContext
from infra.bus.event import EventBus
from infra.bus.message import MessageBus
from infra.bus.types import OutboundMessage
from infra.telemetry import TraceRecorder
from interfaces.channels.telegram import TelegramChannel


class _Tool:
    name = "lookup"
    description = "查询测试数据"
    input_schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    def __init__(self) -> None:
        self.calls = 0

    def run(self, tool_input: dict[str, object]):
        from application.capabilities.tools.base import ToolResult

        self.calls += 1
        return ToolResult(ok=True, content=f"命中:{tool_input['query']}")


class _AsyncLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def generate_async(self, messages, tools=None):
        del messages
        self.calls += 1
        await asyncio.sleep(0.001)
        if self.calls == 1:
            assert tools
            return LLMResult(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-1",
                        name="lookup",
                        arguments_json='{"query":"AI"}',
                        arguments={"query": "AI"},
                    )
                ],
            )
        return LLMResult(content="最终回复")


class _EventSpy:
    def __init__(self) -> None:
        self.events = []

    def on_event(self, event) -> None:
        self.events.append(event)


def test_telegram_message_runs_one_agent_turn_and_records_latencies(tmp_path):
    """一条 Telegram 入站只能产生一轮推理、一条回复和完整耗时记录。"""

    async def scenario() -> None:
        bus = MessageBus()
        event_bus = EventBus()
        llm = _AsyncLLM()
        tool = _Tool()
        from application.capabilities.tools.registry import ToolRegistry

        registry = ToolRegistry()
        registry.register(tool)
        recorder = TraceRecorder(tmp_path / "passive.jsonl")
        agent = Agent(
            system_prompt="测试助手",
            llm_client=llm,
            context=ConversationContext(),
        )
        pipeline = PassiveTurnPipeline(
            agent=agent,
            tool_registry=registry,
            message_bus=bus,
            event_bus=event_bus,
            recorder=recorder,
        )

        event_spy = _EventSpy()
        event_bus.subscribe(event_spy)

        channel = TelegramChannel("test-token")
        channel._context = SimpleNamespace(bus=bus, event_bus=event_bus, log=None)
        loop = AgentLoop(
            bus,
            pipeline,
            event_bus=event_bus,
            poll_interval_ms=1,
        )
        running = asyncio.create_task(loop.run_forever())
        try:
            await channel._handle_update(
                {
                    "message": {
                        "message_id": 1,
                        "chat": {"id": 42, "type": "private"},
                        "from": {"id": 42, "username": "user"},
                        "text": "请查询 AI",
                    }
                }
            )

            deadline = asyncio.get_running_loop().time() + 1
            outbound = None
            while outbound is None and asyncio.get_running_loop().time() < deadline:
                outbound = bus.outbound.consume_one()
                if outbound is None:
                    await asyncio.sleep(0.01)

            assert outbound is not None
            assert bus.outbound.consume_one() is None
            assert isinstance(outbound, OutboundMessage)
            assert outbound.text == "最终回复"
            assert outbound.chat_id == "42"
            assert llm.calls == 2
            assert tool.calls == 1
            assert len(
                [event for event in event_spy.events if event.event_type == "turn_started"]
            ) == 1

            events = [
                json.loads(line)
                for line in (tmp_path / "passive.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            first_token = [event for event in events if event["type"] == "turn_first_token"]
            perf = [event for event in events if event["type"] == "turn_perf"]
            assert len(first_token) == 1
            assert len(perf) == 1
            assert first_token[0]["latency_ms"] >= 0
            assert perf[0]["first_token_latency_ms"] >= 0
            assert perf[0]["full_reply_latency_ms"] >= perf[0]["first_token_latency_ms"]
        finally:
            await loop.stop()
            await asyncio.wait_for(running, timeout=1)

    asyncio.run(scenario())

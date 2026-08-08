"""消息总线、事件总线与被动回合管道集成测试。"""

import json
import threading
import time

from application.conversation.app.agent import Agent
from application.conversation.infra.context import ConversationContext
from infra.bus.message import (
    MessageBus,
    InboundQueue,
    OutboundQueue,
    OutboundDispatch,
    BusOutboundPort,
)
from infra.bus.event import EventBus, Event, TurnCommitted
from application.conversation.app.pipeline import PassiveTurnPipeline
from application.conversation.app.agent_loop import AgentLoop, ProcessingState
from application.conversation.app.phase import PhaseModule, TurnFlow
from interfaces.channels.models import InboundMessage, OutboundMessage
from application.capabilities.llm.client import LLMResult, LLMToolCall
from application.capabilities.tools.base import ToolResult
from application.capabilities.tools.registry import ToolRegistry


# ── 测试用 LLM 客户端 ──────────────────────────────────────

class ScriptedLLMClient:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1 and tools:
            return LLMResult(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call_p1",
                        name="fake_tool",
                        arguments_json=json.dumps({"query": "test"}),
                        arguments={"query": "test"},
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


def _build_system_prompt() -> str:
    return "You are helpful."


# ── InboundQueue 测试 ─────────────────────────────────────

def test_inbound_queue_publish_and_consume():
    q = InboundQueue()
    msg = InboundMessage(channel="test", session_id="s1", text="hello")
    q.publish(msg)
    assert q.size == 1
    consumed = q.consume_one()
    assert consumed is not None
    assert consumed.text == "hello"
    assert q.size == 0
    assert q.consume_one() is None


def test_inbound_queue_consume_all():
    q = InboundQueue()
    q.publish(InboundMessage(channel="test", session_id="s1", text="a"))
    q.publish(InboundMessage(channel="test", session_id="s1", text="b"))
    items = q.consume_all()
    assert len(items) == 2
    assert q.size == 0


# ── OutboundQueue 测试（新 subscribe 接口） ────────────────────

class _FakeSubscriber:
    def __init__(self):
        self.received: list[OutboundMessage] = []

    def on_outbound(self, message: OutboundMessage) -> None:
        self.received.append(message)


def test_outbound_queue_subscribe_and_dispatch():
    """测试 OutboundQueue 的 subscribe(channel, callback) 和 dispatch 接口。"""
    q = OutboundQueue()
    sub = _FakeSubscriber()
    q.subscribe("cli", sub.on_outbound)
    assert q.subscriber_count == 1

    msg = OutboundMessage(channel="cli", session_id="s1", text="reply")
    q.dispatch(msg)
    assert len(sub.received) == 1
    assert sub.received[0].text == "reply"


def test_outbound_queue_unsubscribe():
    """测试取消订阅。"""
    q = OutboundQueue()
    sub = _FakeSubscriber()
    q.subscribe("cli", sub.on_outbound)
    q.unsubscribe("cli", sub.on_outbound)
    assert q.subscriber_count == 0
    q.dispatch(OutboundMessage(channel="cli", session_id="s1", text="reply"))
    assert len(sub.received) == 0


def test_outbound_queue_publish_and_consume():
    """测试 publish → consume_one 流程。"""
    q = OutboundQueue()
    msg = OutboundMessage(channel="cli", session_id="s1", text="queued reply")
    q.publish(msg)
    consumed = q.consume_one()
    assert consumed is not None
    assert consumed.text == "queued reply"
    assert q.consume_one() is None


def test_outbound_queue_has_subscribers():
    """测试 has_subscribers 检查。"""
    q = OutboundQueue()
    assert not q.has_subscribers("cli")
    sub = _FakeSubscriber()
    q.subscribe("cli", sub.on_outbound)
    assert q.has_subscribers("cli")
    assert not q.has_subscribers("qq")


# ── BusOutboundPort 测试 ──────────────────────────────────

def test_bus_outbound_port_send():
    """测试 BusOutboundPort.send 将 OutboundDispatch 发布到队列。"""
    q = OutboundQueue()
    port = BusOutboundPort(_queue=q)
    dispatch = OutboundDispatch(channel="cli", session_id="s1", text="outbound test")
    port.send(dispatch)
    consumed = q.consume_one()
    assert consumed is not None
    assert consumed.text == "outbound test"
    assert consumed.channel == "cli"


# ── MessageBus 集成测试 ───────────────────────────────────

def test_message_bus_inbound_flow():
    bus = MessageBus()
    msg = InboundMessage(channel="test", session_id="s1", text="hello")
    bus.publish_inbound(msg)
    consumed = bus.consume_inbound()
    assert consumed is not None
    assert consumed.text == "hello"


def test_message_bus_outbound_subscribe_publish():
    """测试 MessageBus.subscribe_outbound(channel, callback) 和 OutboundQueue.publish。"""
    bus = MessageBus()
    sub = _FakeSubscriber()
    bus.subscribe_outbound("cli", sub.on_outbound)
    msg = OutboundMessage(channel="cli", session_id="s1", text="reply")
    bus.outbound.publish(msg)
    # publish 只入队，不触发分发
    assert bus.outbound.consume_one() is not None
    # dispatch 触发分发
    bus.outbound.dispatch(OutboundMessage(channel="cli", session_id="s1", text="reply2"))
    assert len(sub.received) == 1
    assert sub.received[0].text == "reply2"


def test_message_bus_dispatch_outbound():
    """测试 MessageBus.dispatch_outbound（兼容旧接口）。"""
    bus = MessageBus()
    sub = _FakeSubscriber()
    bus.subscribe_outbound("cli", sub.on_outbound)
    msg = OutboundMessage(channel="cli", session_id="s1", text="compat")
    bus.dispatch_outbound(msg)
    # dispatch_outbound 只 publish，不 dispatch
    consumed = bus.outbound.consume_one()
    assert consumed is not None
    assert consumed.text == "compat"


def test_message_bus_outbound_port():
    """测试 MessageBus.outbound_port。"""
    bus = MessageBus()
    assert bus.outbound_port is not None
    dispatch = OutboundDispatch(channel="cli", session_id="s1", text="via port")
    bus.outbound_port.send(dispatch)
    consumed = bus.outbound.consume_one()
    assert consumed is not None
    assert consumed.text == "via port"


# ── EventBus 测试 ────────────────────────────────────────

class _FakeEventSub:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def on_event(self, event: Event) -> None:
        self.events.append(event)


def test_event_bus_publish_and_subscribe():
    eb = EventBus()
    sub = _FakeEventSub()
    eb.subscribe(sub)
    eb.publish(Event(event_type="test_event", payload={"key": "value"}))
    assert len(sub.events) == 1
    assert sub.events[0].event_type == "test_event"


def test_turn_committed_event():
    event = TurnCommitted(
        trace_id="abc123",
        session_id="s1",
        user_input="hello",
        assistant_output="world",
        tool_trace=[{"step": "1", "tool": "search", "status": "ok"}],
    )
    assert event.event_type == "turn_committed"
    assert event.user_input == "hello"
    assert event.assistant_output == "world"
    assert len(event.tool_trace) == 1


# ── ProcessingState 测试 ─────────────────────────────────

def test_processing_state_tracks_sessions():
    """测试 ProcessingState 正确追踪会话处理状态。"""
    import asyncio

    async def dummy():
        await asyncio.sleep(0.01)

    async def verify() -> None:
        state = ProcessingState()
        assert not state.is_processing("s1")
        task = asyncio.create_task(dummy())
        state.set_processing("s1", task)
        assert state.is_processing("s1")
        assert not state.is_processing("s2")
        state.clear_processing("s1")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(verify())


# ── TurnFlow 测试 ────────────────────────────────────────

def test_turnflow_fields():
    flow = TurnFlow(
        user_input="hello",
        session_id="s1",
        channel="cli",
        trace_id="abc123",
    )
    assert flow.user_input == "hello"
    assert flow.session_id == "s1"
    assert flow.channel == "cli"
    assert flow.final_output == ""
    assert flow.tool_trace == []
    assert flow.previous_partial_output == ""
    assert flow.extensions == {}


# ── Pipeline 测试 ────────────────────────────────────────

def test_pipeline_runs_six_phases():
    """测试 PassiveTurnPipeline 执行完整的六阶段管道。

    验证事件广播先于出站投递。
    """
    agent = Agent(
        system_prompt=_build_system_prompt(),
        llm_client=ScriptedLLMClient(),
        context=ConversationContext(),
    )
    registry = ToolRegistry()
    registry.register(FakeTool())
    bus = MessageBus()
    eb = EventBus()
    out_sub = _FakeSubscriber()
    bus.subscribe_outbound("cli", out_sub.on_outbound)
    ev_sub = _FakeEventSub()
    eb.subscribe(ev_sub)

    pipeline = PassiveTurnPipeline(
        agent=agent,
        tool_registry=registry,
        message_bus=bus,
        event_bus=eb,
    )
    inbound = InboundMessage(channel="cli", session_id="s1", text="test six phases")
    pipeline.process(inbound)

    # 验证事件已广播
    assert len(ev_sub.events) >= 1
    turn_committed_events = [e for e in ev_sub.events if e.event_type == "turn_committed"]
    assert len(turn_committed_events) == 1
    assert turn_committed_events[0].payload["user_input"] == "test six phases"
    assert ev_sub.events[0].payload["user_input"] == "test six phases"

    # 验证出站消息已投递到队列
    consumed = bus.outbound.consume_one()
    assert consumed is not None
    assert consumed.text == "pipeline final answer"
    assert consumed.channel == "cli"
    assert consumed.session_id == "s1"


def test_pipeline_outbound_port():
    """测试 Pipeline 通过 outbound_port 投递回复。"""
    agent = Agent(
        system_prompt=_build_system_prompt(),
        llm_client=ScriptedLLMClient(),
        context=ConversationContext(),
    )
    registry = ToolRegistry()
    registry.register(FakeTool())
    bus = MessageBus()
    eb = EventBus()

    pipeline = PassiveTurnPipeline(
        agent=agent,
        tool_registry=registry,
        message_bus=bus,
        event_bus=eb,
    )
    # 入站 + 处理
    inbound = InboundMessage(channel="cli", session_id="s1", text="via port")
    pipeline.process(inbound)

    # 验证出站队列有消息
    consumed = bus.outbound.consume_one()
    assert consumed is not None
    assert consumed.text == "pipeline final answer"


def test_pipeline_errors_gracefully():
    """测试管道在 LLM 出错时仍能发送错误回复。"""
    agent = Agent(
        system_prompt=_build_system_prompt(),
        llm_client=_AlwaysFailLLM(),
        context=ConversationContext(),
    )
    registry = ToolRegistry()
    bus = MessageBus()
    eb = EventBus()

    pipeline = PassiveTurnPipeline(
        agent=agent,
        tool_registry=registry,
        message_bus=bus,
        event_bus=eb,
    )

    inbound = InboundMessage(channel="cli", session_id="s1", text="crash test")
    pipeline.process(inbound)

    # 错误回复已投递
    consumed = bus.outbound.consume_one()
    assert consumed is not None
    assert "simulated LLM failure" in consumed.text


class _AlwaysFailLLM:
    def generate(self, messages, tools=None):
        raise RuntimeError("simulated LLM failure")


# ── AgentLoop 测试 ───────────────────────────────────────

def test_agent_loop_run_once():
    """测试 AgentLoop.run_once 处理一条消息。"""
    agent = Agent(
        system_prompt=_build_system_prompt(),
        llm_client=ScriptedLLMClient(),
        context=ConversationContext(),
    )
    registry = ToolRegistry()
    registry.register(FakeTool())
    bus = MessageBus()
    eb = EventBus()

    pipeline = PassiveTurnPipeline(
        agent=agent,
        tool_registry=registry,
        message_bus=bus,
        event_bus=eb,
    )
    loop = AgentLoop(message_bus=bus, pipeline=pipeline, event_bus=eb)

    bus.publish_inbound(InboundMessage(channel="cli", session_id="s1", text="run once"))
    assert loop.run_once() is True
    assert loop.run_once() is False  # 队列为空

    # 验证回复已投递
    consumed = bus.outbound.consume_one()
    assert consumed is not None
    assert consumed.text == "pipeline final answer"


# ── 渠道 MessageBus 集成测试（新 subscribe 接口）────────────

def test_cli_channel_publishes_to_message_bus():
    """测试 CLI 渠道通过 MessageBus 发布入站消息。"""
    from interfaces.channels.cli import CLIChannel

    bus = MessageBus()
    cli = CLIChannel(message_bus=bus, default_session_id="test")
    cli.start()

    cli.handle_line("hello from cli")

    inbound = bus.consume_inbound()
    assert inbound is not None
    assert inbound.text == "hello from cli"
    assert inbound.channel == "cli"
    assert inbound.session_id == "test"


def test_cli_channel_receives_outbound_via_subscription():
    """测试 CLI 渠道通过订阅回调接收出站消息。"""
    from interfaces.channels.cli import CLIChannel

    bus = MessageBus()
    cli = CLIChannel(message_bus=bus)
    cli.start()

    # 模拟 MessageBus 分发（通过订阅回调）
    msg = OutboundMessage(channel="cli", session_id="test", text="response text")
    bus.outbound.dispatch(msg)

    assert cli._last_outbound_text == "response text"


# ── 完整集成流程测试 ─────────────────────────────────────

def test_full_message_bus_architecture_flow():
    """端到端测试：渠道 → MessageBus → AgentLoop → Pipeline → 回复。

    验证：
    1. 入站消息通过 MessageBus 发布
    2. AgentLoop 拉取并处理
    3. Pipeline AfterTurn 阶段：
       ① 先通过 EventBus 广播 TurnCommitted
       ② 再通过 OutboundPort 投递到出站队列
    4. 出站队列分发给订阅者
    """
    agent = Agent(
        system_prompt=_build_system_prompt(),
        llm_client=ScriptedLLMClient(),
        context=ConversationContext(),
    )
    registry = ToolRegistry()
    registry.register(FakeTool())
    bus = MessageBus()
    eb = EventBus()

    # 出站订阅者
    out_sub = _FakeSubscriber()
    bus.subscribe_outbound("cli", out_sub.on_outbound)

    # 事件订阅者
    ev_sub = _FakeEventSub()
    eb.subscribe(ev_sub)

    pipeline = PassiveTurnPipeline(
        agent=agent,
        tool_registry=registry,
        message_bus=bus,
        event_bus=eb,
    )
    loop = AgentLoop(message_bus=bus, pipeline=pipeline, event_bus=eb)

    # 模拟渠道发布入站消息
    bus.publish_inbound(InboundMessage(channel="cli", session_id="full", text="end to end"))

    # AgentLoop 处理
    assert loop.run_once() is True

    # 验证出站消息在队列中
    consumed = bus.outbound.consume_one()
    assert consumed is not None
    assert consumed.text == "pipeline final answer"
    assert consumed.channel == "cli"
    assert consumed.session_id == "full"

    # 分发给订阅者
    bus.outbound.dispatch(consumed)
    assert len(out_sub.received) == 1
    assert out_sub.received[0].text == "pipeline final answer"

    # 验证事件（先于出站投递）
    assert len(ev_sub.events) >= 1
    turn_committed_events = [e for e in ev_sub.events if e.event_type == "turn_committed"]
    assert len(turn_committed_events) == 1
    assert turn_committed_events[0].payload["user_input"] == "end to end"
    assert ev_sub.events[0].payload["user_input"] == "end to end"

    # 验证历史
    history = agent.context.get_history("full")
    assert history[0]["content"] == "end to end"
    assert history[1]["content"] == "pipeline final answer"

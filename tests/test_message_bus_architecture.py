"""消息总线、事件总线与被动回合管道集成测试。"""

import json
import threading
import time

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
from flow_agent.messaging.message_bus import MessageBus, InboundQueue, OutboundQueue
from flow_agent.messaging.event_bus import EventBus, Event, TurnCommitted
from flow_agent.core.passive_turn_pipeline import PassiveTurnPipeline
from flow_agent.core.agent_loop import AgentLoop
from flow_agent.core.phase_module import PhaseModule, TurnFlow
from flow_agent.channels.models import InboundMessage, OutboundMessage
from flow_agent.llm.client import LLMResult, LLMToolCall
from flow_agent.tools.base import ToolResult
from flow_agent.tools.registry import ToolRegistry
from flow_agent.dashboard.store import InMemoryDashboardStore


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


def _build_settings() -> Settings:
    return Settings(
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


# ── OutboundQueue 测试 ────────────────────────────────────

class _FakeSubscriber:
    def __init__(self):
        self.received: list[OutboundMessage] = []

    def on_outbound(self, message: OutboundMessage) -> None:
        self.received.append(message)


def test_outbound_queue_subscribe_and_dispatch():
    q = OutboundQueue()
    sub = _FakeSubscriber()
    q.subscribe(sub)
    assert q.subscriber_count == 1

    msg = OutboundMessage(channel="test", session_id="s1", text="reply")
    q.dispatch(msg)
    assert len(sub.received) == 1
    assert sub.received[0].text == "reply"


def test_outbound_queue_unsubscribe():
    q = OutboundQueue()
    sub = _FakeSubscriber()
    q.subscribe(sub)
    q.unsubscribe(sub)
    assert q.subscriber_count == 0
    q.dispatch(OutboundMessage(channel="test", session_id="s1", text="reply"))
    assert len(sub.received) == 0


# ── MessageBus 集成测试 ───────────────────────────────────

def test_message_bus_inbound_flow():
    bus = MessageBus()
    msg = InboundMessage(channel="cli", session_id="s1", text="hello")
    bus.publish_inbound(msg)
    consumed = bus.consume_inbound()
    assert consumed is not None
    assert consumed.text == "hello"


def test_message_bus_outbound_flow():
    bus = MessageBus()
    sub = _FakeSubscriber()
    bus.subscribe_outbound(sub)
    msg = OutboundMessage(channel="cli", session_id="s1", text="reply")
    bus.dispatch_outbound(msg)
    assert len(sub.received) == 1
    assert sub.received[0].text == "reply"


# ── EventBus 测试 ─────────────────────────────────────────

class _FakeEventSub:
    def __init__(self):
        self.events: list[Event] = []

    def on_event(self, event: Event) -> None:
        self.events.append(event)


def test_event_bus_publish_and_fanout():
    bus = EventBus()
    sub1 = _FakeEventSub()
    sub2 = _FakeEventSub()
    bus.subscribe(sub1)
    bus.subscribe(sub2)

    event = Event(event_type="test_event", trace_id="abc123")
    bus.publish(event)

    assert len(sub1.events) == 1
    assert len(sub2.events) == 1
    assert sub1.events[0].event_type == "test_event"
    assert sub1.events[0].trace_id == "abc123"


def test_turn_committed_event():
    event = TurnCommitted(
        trace_id="t1",
        session_id="s1",
        user_input="hello",
        assistant_output="hi",
        tool_trace=[{"step": "1", "tool": "fake_tool", "status": "ok"}],
    )
    assert event.event_type == "turn_committed"
    assert event.payload["user_input"] == "hello"
    assert event.payload["assistant_output"] == "hi"
    assert len(event.payload["tool_trace"]) == 1


# ── PhaseModule 测试 ──────────────────────────────────────

class _TestPhaseModule:
    def __init__(self, name: str = "test"):
        self._name = name
        self.calls: list[str] = []

    @property
    def name(self) -> str:
        return self._name

    def on_before_turn(self, flow: TurnFlow) -> None:
        self.calls.append("before_turn")

    def on_before_reasoning(self, flow: TurnFlow) -> None:
        self.calls.append("before_reasoning")

    def on_prompt_render(self, flow: TurnFlow) -> None:
        self.calls.append("prompt_render")

    def on_after_reasoning(self, flow: TurnFlow) -> None:
        self.calls.append("after_reasoning")

    def on_after_turn(self, flow: TurnFlow) -> None:
        self.calls.append("after_turn")


# ── PassiveTurnPipeline 完整流程测试 ─────────────────────

def test_passive_turn_pipeline_full_flow():
    """测试完整的六阶段管道流程。"""
    agent = Agent(
        settings=_build_settings(),
        llm_client=ScriptedLLMClient(),
        context=ConversationContext(),
    )
    registry = ToolRegistry()
    registry.register(FakeTool())
    bus = MessageBus()
    eb = EventBus()
    dashboard = InMemoryDashboardStore()

    pipeline = PassiveTurnPipeline(
        agent=agent,
        tool_registry=registry,
        message_bus=bus,
        event_bus=eb,
        dashboard=dashboard,
    )

    # 注册阶段模块
    mod = _TestPhaseModule()
    pipeline.register_phase_module(mod)

    inbound = InboundMessage(channel="cli", session_id="s1", text="hello pipeline")

    # 处理消息
    pipeline.process(inbound)

    # 验证六个阶段都被调用了
    assert sorted(mod.calls) == [
        "after_reasoning",
        "after_turn",
        "before_reasoning",
        "before_turn",
        "prompt_render",
    ]

    # 验证阶段事件被记录
    events = dashboard.all_events()
    phase_starts = [e for e in events if e.get("type") == "turn_phase_start"]
    phase_ends = [e for e in events if e.get("type") == "turn_phase_end"]
    expected_phases = {
        "before_turn", "before_reasoning", "prompt_render",
        "reasoner", "after_reasoning", "after_turn",
    }
    assert {e.get("phase") for e in phase_starts} >= expected_phases
    assert {e.get("phase") for e in phase_ends} >= expected_phases

    # 验证对话已提交
    history = agent.context.get_history("s1")
    assert len(history) == 2
    assert history[0]["content"] == "hello pipeline"
    assert history[1]["content"] == "pipeline final answer"


def test_passive_turn_pipeline_dispatches_outbound():
    """测试 AfterTurn 阶段通过 MessageBus 投递出站消息。"""
    agent = Agent(
        settings=_build_settings(),
        llm_client=ScriptedLLMClient(),
        context=ConversationContext(),
    )
    registry = ToolRegistry()
    registry.register(FakeTool())
    bus = MessageBus()
    eb = EventBus()

    # 订阅出站消息
    sub = _FakeSubscriber()
    bus.subscribe_outbound(sub)

    pipeline = PassiveTurnPipeline(
        agent=agent,
        tool_registry=registry,
        message_bus=bus,
        event_bus=eb,
    )

    inbound = InboundMessage(channel="cli", session_id="s1", text="hello")
    pipeline.process(inbound)

    # 验证出站回复已投递
    assert len(sub.received) == 1
    assert sub.received[0].text == "pipeline final answer"
    assert sub.received[0].channel == "cli"
    assert sub.received[0].session_id == "s1"
    assert sub.received[0].metadata.get("trace_id") is not None


def test_passive_turn_pipeline_publishes_turn_committed_event():
    """测试 AfterTurn 阶段通过 EventBus 广播 TurnCommitted 事件。"""
    agent = Agent(
        settings=_build_settings(),
        llm_client=ScriptedLLMClient(),
        context=ConversationContext(),
    )
    registry = ToolRegistry()
    registry.register(FakeTool())
    bus = MessageBus()
    eb = EventBus()

    # 订阅事件
    sub = _FakeEventSub()
    eb.subscribe(sub)

    pipeline = PassiveTurnPipeline(
        agent=agent,
        tool_registry=registry,
        message_bus=bus,
        event_bus=eb,
    )

    inbound = InboundMessage(channel="cli", session_id="s1", text="event test")
    pipeline.process(inbound)

    # 验证 TurnCommitted 事件已广播
    assert len(sub.events) == 1
    event = sub.events[0]
    assert event.event_type == "turn_committed"
    assert event.payload["user_input"] == "event test"
    assert event.payload["assistant_output"] == "pipeline final answer"


# ── 收尾双动作独立性测试 ────────────────────────────────

def test_after_turn_dual_actions_independent():
    """测试 AfterTurn 的 EventBus 广播和 MessageBus 投递是独立的。

    即使 EventBus 订阅者抛出异常，MessageBus 投递仍应成功。
    """
    agent = Agent(
        settings=_build_settings(),
        llm_client=ScriptedLLMClient(),
        context=ConversationContext(),
    )
    registry = ToolRegistry()
    registry.register(FakeTool())
    bus = MessageBus()
    eb = EventBus()

    # 两个订阅者：一个正常，一个会抛出异常
    sub_ok = _FakeEventSub()
    class _BrokenSub:
        def on_event(self, event: Event) -> None:
            raise RuntimeError("broken event handler")
    broken = _BrokenSub()
    eb.subscribe(sub_ok)
    eb.subscribe(broken)

    # 出站订阅者
    out_sub = _FakeSubscriber()
    bus.subscribe_outbound(out_sub)

    pipeline = PassiveTurnPipeline(
        agent=agent,
        tool_registry=registry,
        message_bus=bus,
        event_bus=eb,
    )

    inbound = InboundMessage(channel="cli", session_id="s1", text="test")
    # 不应抛出异常
    pipeline.process(inbound)

    # EventBus: 正常订阅者仍能收到事件
    assert len(sub_ok.events) == 1

    # MessageBus: 出站投递仍成功
    assert len(out_sub.received) == 1
    assert out_sub.received[0].text == "pipeline final answer"


# ── AgentLoop 测试 ────────────────────────────────────────

def test_agent_loop_run_once():
    agent = Agent(
        settings=_build_settings(),
        llm_client=ScriptedLLMClient(),
        context=ConversationContext(),
    )
    registry = ToolRegistry()
    registry.register(FakeTool())
    bus = MessageBus()
    eb = EventBus()
    out_sub = _FakeSubscriber()
    bus.subscribe_outbound(out_sub)

    pipeline = PassiveTurnPipeline(
        agent=agent,
        tool_registry=registry,
        message_bus=bus,
        event_bus=eb,
    )
    loop = AgentLoop(message_bus=bus, pipeline=pipeline)

    # 无消息时 run_once 返回 False
    assert loop.run_once() is False

    # 发布消息后 run_once 返回 True
    bus.publish_inbound(InboundMessage(channel="cli", session_id="s1", text="via loop"))
    assert loop.run_once() is True

    # 出站消息已投递
    assert len(out_sub.received) == 1
    assert out_sub.received[0].text == "pipeline final answer"


def test_agent_loop_run_forever_stops():
    """测试 run_forever 可以通过 stop 停止。"""
    agent = Agent(
        settings=_build_settings(),
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
    loop = AgentLoop(message_bus=bus, pipeline=pipeline)

    # 启动后台线程
    loop.start_background()
    assert loop.running

    # 发布消息，等待处理
    bus.publish_inbound(InboundMessage(channel="cli", session_id="s1", text="bg test"))
    time.sleep(0.3)

    # 停止
    loop.stop()
    assert not loop.running

    # 验证消息被处理了
    history = agent.context.get_history("s1")
    assert len(history) == 2
    assert history[1]["content"] == "pipeline final answer"


# ── 错误处理测试 ─────────────────────────────────────────

class _AlwaysFailLLM:
    def generate(self, messages, tools=None):
        raise RuntimeError("simulated LLM failure")


def test_pipeline_handles_errors_gracefully():
    """测试管道在 LLM 出错时仍能通过 MessageBus 发送错误回复。"""
    agent = Agent(
        settings=_build_settings(),
        llm_client=_AlwaysFailLLM(),
        context=ConversationContext(),
    )
    registry = ToolRegistry()
    bus = MessageBus()
    eb = EventBus()
    out_sub = _FakeSubscriber()
    bus.subscribe_outbound(out_sub)

    pipeline = PassiveTurnPipeline(
        agent=agent,
        tool_registry=registry,
        message_bus=bus,
        event_bus=eb,
    )

    inbound = InboundMessage(channel="cli", session_id="s1", text="crash test")
    # 不应抛出未捕获异常
    pipeline.process(inbound)

    # 错误回复已投递
    assert len(out_sub.received) == 1
    assert "simulated LLM failure" in out_sub.received[0].text


# ── 渠道 MessageBus 集成测试 ────────────────────────────

def test_cli_channel_publishes_to_message_bus():
    """测试 CLI 渠道通过 MessageBus 发布入站消息。"""
    from flow_agent.channels.cli import CLIChannel

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
    """测试 CLI 渠道通过订阅接收出站消息。"""
    from flow_agent.channels.cli import CLIChannel

    bus = MessageBus()
    cli = CLIChannel(message_bus=bus)
    cli.start()

    bus.dispatch_outbound(OutboundMessage(
        channel="cli", session_id="test", text="response text"
    ))

    assert cli._last_outbound_text == "response text"


# ── 完整集成流程测试 ─────────────────────────────────────

def test_full_message_bus_architecture_flow():
    """端到端测试：渠道 → MessageBus → AgentLoop → Pipeline → 回复。

    验证：
    1. 入站消息通过 MessageBus 发布
    2. AgentLoop 拉取并处理
    3. 出站回复通过 MessageBus 投递
    4. 事件通过 EventBus 广播
    """
    agent = Agent(
        settings=_build_settings(),
        llm_client=ScriptedLLMClient(),
        context=ConversationContext(),
    )
    registry = ToolRegistry()
    registry.register(FakeTool())
    bus = MessageBus()
    eb = EventBus()

    # 出站订阅者
    out_sub = _FakeSubscriber()
    bus.subscribe_outbound(out_sub)

    # 事件订阅者
    ev_sub = _FakeEventSub()
    eb.subscribe(ev_sub)

    pipeline = PassiveTurnPipeline(
        agent=agent,
        tool_registry=registry,
        message_bus=bus,
        event_bus=eb,
    )
    loop = AgentLoop(message_bus=bus, pipeline=pipeline)

    # 模拟渠道发布入站消息
    bus.publish_inbound(InboundMessage(channel="cli", session_id="full", text="end to end"))

    # AgentLoop 处理
    assert loop.run_once() is True

    # 验证出站
    assert len(out_sub.received) == 1
    assert out_sub.received[0].text == "pipeline final answer"
    assert out_sub.received[0].channel == "cli"
    assert out_sub.received[0].session_id == "full"

    # 验证事件
    assert len(ev_sub.events) == 1
    assert ev_sub.events[0].event_type == "turn_committed"
    assert ev_sub.events[0].payload["user_input"] == "end to end"

    # 验证历史
    history = agent.context.get_history("full")
    assert history[0]["content"] == "end to end"
    assert history[1]["content"] == "pipeline final answer"
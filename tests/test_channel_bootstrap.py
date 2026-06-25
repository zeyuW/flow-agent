"""通道启动与 MessagePushTool 单元测试。"""

import asyncio
import json
from dataclasses import dataclass, field

import pytest

from flow_agent.channels.base import Channel, ChannelStatus, MessageBusChannel
from flow_agent.channels.models import InboundMessage, OutboundMessage
from flow_agent.channels.channel_bootstrap import start_channels, stop_channels
from flow_agent.tools.message_push import MessagePushTool


# ── 模拟 MessageBus ──

@dataclass
class FakeMessageBus:
    """轻量级 MessageBus 模拟，用于通道测试。"""
    inbound: list[InboundMessage] = field(default_factory=list)
    outbound: list[OutboundMessage] = field(default_factory=list)
    subscribers: dict[str, list] = field(default_factory=dict)

    def publish_inbound(self, msg: InboundMessage) -> None:
        self.inbound.append(msg)

    def subscribe_outbound(self, channel: str, callback) -> None:
        self.subscribers.setdefault(channel, []).append(callback)

    def unsubscribe_outbound(self, channel: str, callback) -> None:
        subs = self.subscribers.get(channel, [])
        if callback in subs:
            subs.remove(callback)


# ── 模拟通道 ──

@dataclass
class FakeChannel(MessageBusChannel):
    """测试用模拟通道。"""
    channel_name: str = "fake"
    message_bus: FakeMessageBus | None = None
    _running: bool = False
    started: bool = False
    stopped: bool = False

    @property
    def name(self) -> str:
        return self.channel_name

    def start(self) -> None:
        self._running = True
        self.started = True
        if self.message_bus:
            self.message_bus.subscribe_outbound(self.name, self._on_response)

    def stop(self) -> None:
        self._running = False
        self.stopped = True
        if self.message_bus:
            self.message_bus.unsubscribe_outbound(self.name, self._on_response)

    def status(self) -> ChannelStatus:
        return ChannelStatus(running=self._running)

    def _on_response(self, message: OutboundMessage) -> None:
        pass

    def on_outbound(self, message: OutboundMessage) -> None:
        pass

    def send(self, *, chat_id: str, text: str) -> None:
        pass  # 由 MessagePushTool 调用


# ── 通道启动测试 (spec 1a-1f) ──

def test_start_channels_launches_all():
    bus = FakeMessageBus()
    ch1 = FakeChannel(channel_name="ch1", message_bus=bus)
    ch2 = FakeChannel(channel_name="ch2", message_bus=bus)

    async def _test():
        started = await start_channels(channels=[ch1, ch2], message_bus=bus)
        assert len(started) == 2
        assert ch1.started is True
        assert ch2.started is True
        # 每个通道都应订阅了出站消息
        assert "ch1" in bus.subscribers
        assert "ch2" in bus.subscribers

    asyncio.run(_test())


def test_stop_channels_stops_all():
    bus = FakeMessageBus()
    ch1 = FakeChannel(channel_name="ch1", message_bus=bus)
    ch2 = FakeChannel(channel_name="ch2", message_bus=bus)

    async def _test():
        started = await start_channels(channels=[ch1, ch2], message_bus=bus)
        await stop_channels(started)
        assert ch1.stopped is True
        assert ch2.stopped is True

    asyncio.run(_test())


def test_start_channels_handles_failure_gracefully():
    bus = FakeMessageBus()

    class BrokenChannel(FakeChannel):
        def start(self) -> None:
            raise RuntimeError("boom")

    ch1 = FakeChannel(channel_name="ok", message_bus=bus)
    ch2 = BrokenChannel(channel_name="broken", message_bus=bus)

    async def _test():
        started = await start_channels(channels=[ch1, ch2], message_bus=bus)
        # ch1 应成功，ch2 失败被跳过
        assert len(started) == 1
        assert "ok" in started

    asyncio.run(_test())


# ── MessagePushTool 测试 (spec 4a-4d) ──

def test_push_tool_registers_channels():
    tool = MessagePushTool()

    def fake_send(*, chat_id: str, text: str) -> None:
        pass

    tool.register_channel("cli", send=fake_send)
    tool.register_channel("qq", send=fake_send, send_file=fake_send)

    assert "cli" in tool._senders
    assert "send" in tool._senders["cli"]
    assert "send_file" not in tool._senders["cli"]
    assert "send_file" in tool._senders["qq"]


def test_push_tool_schema_is_valid():
    tool = MessagePushTool()
    schema = tool.schema()
    assert schema["function"]["name"] == "message_push"
    assert "channel" in schema["function"]["parameters"]["required"]


def test_push_tool_execute_send_text():
    tool = MessagePushTool()
    sent: list[dict] = []

    def capture_send(*, chat_id: str, text: str) -> None:
        sent.append({"chat_id": chat_id, "text": text})

    tool.register_channel("cli", send=capture_send)
    result = tool.execute({
        "channel": "cli",
        "chat_id": "user1",
        "text": "hello world",
    })
    assert len(sent) == 1
    assert sent[0]["text"] == "hello world"
    assert "文本已发送" in result


def test_push_tool_execute_unknown_channel():
    tool = MessagePushTool()
    result = tool.execute({"channel": "unknown", "chat_id": "u1", "text": "hi"})
    assert "未注册" in result


def test_push_tool_execute_no_text():
    tool = MessagePushTool()
    sent: list[dict] = []

    def capture_send(*, chat_id: str, text: str) -> None:
        sent.append({"chat_id": chat_id, "text": text})

    tool.register_channel("cli", send=capture_send)
    result = tool.execute({"channel": "cli", "chat_id": "u1", "text": ""})
    assert len(sent) == 0
    assert "无内容发送" in result


# ── QQBotChannel 基本测试 ──

def test_qqbot_channel_attributes():
    from flow_agent.channels.qqbot import QQBotChannel
    channel = QQBotChannel(app_id="123", token="tok", allowed_users={100})
    assert channel.name == "qq"
    status = channel.status()
    assert status.running is False


def test_qqbot_channel_start_stop():
    from flow_agent.channels.qqbot import QQBotChannel
    bus = FakeMessageBus()
    channel = QQBotChannel(app_id="123", token="tok", message_bus=bus)
    channel.start()
    assert channel._running is True
    channel.stop()
    assert channel._running is False


def test_qqbot_extract_text():
    from flow_agent.channels.qqbot import QQBotChannel
    channel = QQBotChannel(app_id="123", token="tok")
    # 测试去除内嵌标签
    assert channel._extract_text("你好世界") == "你好世界"
    assert channel._extract_text("<@!12345> 你好") == "你好"
    assert channel._extract_text("") == ""

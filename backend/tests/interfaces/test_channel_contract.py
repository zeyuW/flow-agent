from __future__ import annotations

import logging
from pathlib import Path

from infra.bus.types import ChannelDeliveryResult, OutboundMessage
from interfaces.channels.base import (
    BaseChannelAdapter,
    ChannelCapabilities,
    ChannelContext,
)


class RecordingBus:
    def __init__(self) -> None:
        self.subscriptions: list[tuple[str, object]] = []
        self.unsubscriptions: list[tuple[str, object]] = []
        self.inbound: list[object] = []

    def subscribe_outbound(self, channel: str, callback) -> None:
        self.subscriptions.append((channel, callback))

    def unsubscribe_outbound(self, channel: str, callback) -> None:
        self.unsubscriptions.append((channel, callback))

    def publish_inbound(self, message) -> None:
        self.inbound.append(message)


class RecordingEventBus:
    pass


class FakeChannel(BaseChannelAdapter):
    name = "fake"
    capabilities = ChannelCapabilities(text=True, file=False, image=False)

    def __init__(self) -> None:
        super().__init__()
        self.platform_starts = 0
        self.platform_stops = 0
        self.join_calls: list[float | None] = []
        self.deliveries: list[OutboundMessage] = []

    def _start_platform(self) -> None:
        self.platform_starts += 1

    def _stop_platform(self) -> None:
        self.platform_stops += 1

    def join(self, timeout: float | None = None) -> None:
        self.join_calls.append(timeout)

    def send_text(self, *, recipient_id: str, text: str) -> ChannelDeliveryResult:
        del recipient_id, text
        return ChannelDeliveryResult(delivered=True)

    def _deliver_outbound(self, message: OutboundMessage) -> ChannelDeliveryResult:
        self.deliveries.append(message)
        return ChannelDeliveryResult(delivered=True)


def _context(tmp_path: Path, bus: RecordingBus) -> ChannelContext:
    return ChannelContext(
        bus=bus,
        event_bus=RecordingEventBus(),
        log=logging.getLogger("test-channel"),
        attachment_dir=tmp_path,
    )


def test_base_channel_subscribes_and_unsubscribes_outbound_callback(
    tmp_path: Path,
):
    bus = RecordingBus()
    channel = FakeChannel()

    channel.start(_context(tmp_path, bus))

    assert [name for name, _ in bus.subscriptions] == ["fake"]
    assert channel.platform_starts == 1
    assert channel.status().running is True

    channel.stop()

    assert [name for name, _ in bus.unsubscriptions] == ["fake"]
    assert channel.platform_stops == 1
    assert channel.status().running is False


def test_base_channel_lifecycle_is_idempotent(tmp_path: Path):
    bus = RecordingBus()
    channel = FakeChannel()
    context = _context(tmp_path, bus)

    channel.start(context)
    channel.start(context)
    channel.stop()
    channel.stop()
    channel.join(timeout=3.0)

    assert len(bus.subscriptions) == 1
    assert len(bus.unsubscriptions) == 1
    assert channel.platform_starts == 1
    assert channel.platform_stops == 1
    assert channel.join_calls == [3.0]


def test_base_channel_publishes_normalized_inbound_message(
    tmp_path: Path,
):
    bus = RecordingBus()
    channel = FakeChannel()
    channel.start(_context(tmp_path, bus))

    channel.publish_inbound(
        session_id="fake:chat-1",
        chat_id="chat-1",
        sender_id="user-1",
        text="你好",
        media=["/tmp/photo.png"],
        metadata={"provider_message_id": "m-1"},
    )

    message = bus.inbound[0]
    assert message.channel == "fake"
    assert message.session_id == "fake:chat-1"
    assert message.chat_id == "chat-1"
    assert message.sender == "user-1"
    assert message.text == "你好"
    assert message.media == ["/tmp/photo.png"]
    assert message.metadata == {"provider_message_id": "m-1"}

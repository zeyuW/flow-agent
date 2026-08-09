from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from infra.config import ChannelsConfig
from interfaces.channels.base import ChannelContext, ChannelStatus
from interfaces.channels.service import ChannelService


class FakeEventBus:
    pass


class FakeBus:
    def subscribe_outbound(self, channel, callback) -> None:
        del channel, callback

    def unsubscribe_outbound(self, channel, callback) -> None:
        del channel, callback


def _context(tmp_path: Path) -> ChannelContext:
    import logging

    return ChannelContext(
        bus=FakeBus(),
        event_bus=FakeEventBus(),
        log=logging.getLogger("test-channel-service"),
        attachment_dir=tmp_path,
    )


@dataclass
class RecordingChannel:
    name: str
    fail_on_start: bool = False
    order: list[str] | None = None

    def __post_init__(self) -> None:
        self.events: list[str] = []

    @property
    def capabilities(self):
        return None

    def start(self, context: ChannelContext) -> None:
        del context
        self.events.append("start")
        if self.fail_on_start:
            raise RuntimeError(f"{self.name} start failed")

    def stop(self) -> None:
        self.events.append("stop")
        if self.order is not None:
            self.order.append(f"{self.name}:stop")

    def join(self, timeout: float | None = None) -> None:
        self.events.append(f"join:{timeout}")

    def status(self) -> ChannelStatus:
        return ChannelStatus(running="start" in self.events and "stop" not in self.events)


def test_channel_service_builds_only_enabled_channels(tmp_path: Path):
    service = ChannelService()
    created: list[RecordingChannel] = []

    def factory(options, context):
        del context
        channel = RecordingChannel(name=str(options["name"]))
        created.append(channel)
        return channel

    service.register("fake", factory)
    service.build_enabled(
        ChannelsConfig(
            adapters={
                "fake": {"enabled": True, "name": "fake"},
                "off": {"enabled": False, "name": "off"},
            }
        ),
        _context(tmp_path),
    )

    assert [adapter.name for adapter in service.adapters()] == ["fake"]
    assert [channel.name for channel in created] == ["fake"]


def test_channel_service_rejects_duplicate_registration():
    service = ChannelService()
    factory = lambda options, context: (options, context)

    service.register("fake", factory)

    with pytest.raises(ValueError, match="fake"):
        service.register("fake", factory)


def test_channel_service_rolls_back_started_channels_in_reverse_order(
    tmp_path: Path,
):
    service = ChannelService()
    first = RecordingChannel("first")
    second = RecordingChannel("second", fail_on_start=True)
    service.register("first", lambda options, context: first)
    service.register("second", lambda options, context: second)
    service.build_enabled(
        ChannelsConfig(
            adapters={
                "first": {"enabled": True},
                "second": {"enabled": True},
            }
        ),
        _context(tmp_path),
    )

    with pytest.raises(RuntimeError, match="second start failed"):
        service.start_all()

    assert first.events == ["start", "stop"]
    assert second.events == ["start"]


def test_channel_service_stops_and_joins_in_reverse_order(tmp_path: Path):
    service = ChannelService()
    order: list[str] = []
    first = RecordingChannel("first", order=order)
    second = RecordingChannel("second", order=order)
    service.register("first", lambda options, context: first)
    service.register("second", lambda options, context: second)
    service.build_enabled(
        ChannelsConfig(
            adapters={
                "first": {"enabled": True},
                "second": {"enabled": True},
            }
        ),
        _context(tmp_path),
    )
    service.start_all()
    service.stop_all()
    service.join_all(timeout=3.0)

    assert first.events[:2] == ["start", "stop"]
    assert second.events[:2] == ["start", "stop"]
    assert order == ["second:stop", "first:stop"]
    assert first.events[2].startswith("join:")
    assert second.events[2].startswith("join:")
    assert float(first.events[2].split(":", 1)[1]) <= 3.0
    assert float(second.events[2].split(":", 1)[1]) <= 3.0

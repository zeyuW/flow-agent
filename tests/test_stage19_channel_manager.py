from dataclasses import dataclass

from flow_agent.channels.base import ChannelStatus
from flow_agent.channels.channel_manager import ChannelManager


@dataclass(slots=True)
class DummyChannel:
    name: str = "dummy"
    running: bool = False

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def status(self) -> ChannelStatus:
        return ChannelStatus(running=self.running, last_error=None)


def test_channel_manager_start_stop_status():
    mgr = ChannelManager()
    channel = DummyChannel()
    mgr.register(channel)
    mgr.start("dummy")
    status = mgr.status()
    assert status["dummy"]["running"] is True
    mgr.stop("dummy")
    status = mgr.status()
    assert status["dummy"]["running"] is False
    metrics = mgr.metrics.snapshot()
    assert metrics["channel.dummy.start_ok"] == 1
    assert metrics["channel.dummy.stop_ok"] == 1

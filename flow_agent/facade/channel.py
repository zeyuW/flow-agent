from dataclasses import dataclass

from flow_agent.channels.base import Channel
from flow_agent.channels.base import ChannelStatus


@dataclass(slots=True)
class ChannelFacade:
    channels: dict[str, Channel]

    def start(self, name: str) -> None:
        self.channels[name].start()

    def stop(self, name: str) -> None:
        self.channels[name].stop()

    def status(self, name: str) -> ChannelStatus:
        return self.channels[name].status()

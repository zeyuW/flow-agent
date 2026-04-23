from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from flow_agent.channels.models import InboundMessage, OutboundMessage


OutboundSender = Callable[[OutboundMessage], None]
InboundHandler = Callable[[InboundMessage], OutboundMessage | None]


@dataclass(slots=True)
class ChannelStatus:
    running: bool
    last_error: str | None = None


class Channel(Protocol):
    """Channel abstraction for inbound/outbound messaging."""

    @property
    def name(self) -> str:
        ...

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def status(self) -> ChannelStatus:
        ...


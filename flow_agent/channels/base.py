from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from flow_agent.channels.models import InboundMessage, OutboundMessage, OutboundSubscriber


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


class MessageBusChannel(Channel, OutboundSubscriber):
    """基于 MessageBus 的渠道基类。

    实现 OutboundSubscriber 协议，支持：
    - 入站：通过 MessageBus.publish_inbound 发布消息
    - 出站：通过 subscribe_outbound 订阅，on_outbound 回调发送消息
    """

    def on_outbound(self, message: OutboundMessage) -> None:
        """收到出站消息时，调用平台 API 发送给用户。"""
        raise NotImplementedError
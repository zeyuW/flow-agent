from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from application.conversation.domain.channel_message import InboundMessage
from infra.bus.types import OutboundMessage


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


class MessageBusChannel(Channel):
    """基于 MessageBus 的渠道基类。

    支持：
    - 入站：通过 MessageBus.publish_inbound 发布消息
    - 出站：通过 subscribe_outbound 注册 _on_response 回调
            MessageBus 后台 dispatch_outbound 任务调用回调发送消息
    """

    def on_outbound(self, message: OutboundMessage) -> None:
        """收到出站消息时，调用平台 API 发送给用户。

        兼容旧接口，子类应重写 _on_response 方法。
        """
        raise NotImplementedError

"""消息总线对外提供的统一消息类型和角色契约。

本模块只描述跨业务共享的消息数据结构与发送、消费协议；渠道适配器和
具体业务处理逻辑不放在这里。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class SendMessage:
    """一条等待可靠发送到外部渠道的消息。"""

    channel: str
    recipient_id: str
    text: str
    conversation_id: str = ""
    message_id: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SendResult:
    """消息进入可靠传输流程后的结果。"""

    message_id: str
    accepted: bool
    attempts: int = 0
    error: str = ""
    uncertain: bool = False


@runtime_checkable
class MessageSender(Protocol):
    """消息发送设施提供的最小角色。"""

    def send(self, message: SendMessage) -> SendResult:
        """将消息交给可靠消息传输设施。"""

        ...


@dataclass(frozen=True, slots=True)
class ReceivedMessage:
    """从消息传输设施读取的一条统一消息。"""

    message_id: str
    kind: str
    channel: str
    conversation_id: str
    text: str
    sender_id: str = ""
    media: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@runtime_checkable
class MessageConsumer(Protocol):
    """消息消费设施提供的最小角色。"""

    async def receive(self, poll_interval_ms: int = 100) -> ReceivedMessage:
        """等待并读取一条消息。"""

        ...

    async def ack(self, message_id: str) -> None:
        """确认消息已经交给业务处理。"""

        ...

    async def nack(self, message_id: str, *, retry: bool = True) -> None:
        """拒绝消息并选择是否交给技术重试。"""

        ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class OutboundMessage:
    """已经由应用层生成、等待渠道发送的消息。"""

    channel: str
    session_id: str
    text: str
    chat_id: str = ""
    delivery_id: str = ""
    thinking: str | None = None
    media: list[str] = field(default_factory=list)
    sent_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ChannelDeliveryResult:
    """渠道适配器返回的稳定投递结果。"""

    delivered: bool
    retryable: bool = True
    uncertain: bool = False
    error: str = ""

    def __bool__(self) -> bool:
        return self.delivered

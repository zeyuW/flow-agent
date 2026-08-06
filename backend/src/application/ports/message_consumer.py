"""业务层消费消息的端口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable


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
    """只暴露消息消费和确认能力的端口。"""

    async def receive(self, poll_interval_ms: int = 100) -> ReceivedMessage:
        """等待并读取一条消息。"""

        ...

    async def ack(self, message_id: str) -> None:
        """确认消息已经交给业务处理。"""

        ...

    async def nack(self, message_id: str, *, retry: bool = True) -> None:
        """拒绝消息并选择是否交给技术重试。"""

        ...

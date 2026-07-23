from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class InboundMessage:
    """入站消息：从外部渠道接收的消息"""

    channel: str
    session_id: str
    text: str
    sender: str = ""  # 发送者标识（用户 ID 或用户名）
    media: list[str] = field(default_factory=list)  # 媒体文件路径列表
    received_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class OutboundMessage:
    """出站消息：发送到外部渠道的消息"""

    channel: str
    session_id: str
    text: str
    chat_id: str = ""
    delivery_id: str = ""
    thinking: str | None = None  # 思考过程（用于流式输出）
    media: list[str] = field(default_factory=list)  # 媒体文件路径列表
    sent_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ChannelDeliveryResult:
    """渠道适配器返回的单次投递判断。"""

    delivered: bool
    retryable: bool = True
    uncertain: bool = False
    error: str = ""

    def __bool__(self) -> bool:
        return self.delivered


class OutboundSubscriber(Protocol):
    """出站消息订阅者协议：渠道适配器实现此接口来接收待发送的回复。"""

    def on_outbound(self, message: OutboundMessage) -> None:
        ...

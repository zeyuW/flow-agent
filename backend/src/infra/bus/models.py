"""投递领域的出站消息与渠道回执。"""

from dataclasses import dataclass, field
from datetime import datetime, timezone


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

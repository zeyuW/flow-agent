"""渠道进入对话模块前使用的入站消息模型。"""

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class InboundMessage:
    """消息总线中的渠道入站消息。"""

    channel: str
    session_id: str
    text: str
    sender: str = ""
    media: list[str] = field(default_factory=list)
    received_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, object] = field(default_factory=dict)

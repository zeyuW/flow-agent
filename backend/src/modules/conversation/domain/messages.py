"""对话模块的稳定入站消息模型。"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Mapping


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    """渠道适配完成后交给对话用例的用户消息。"""

    channel: str
    conversation_id: str
    text: str
    sender_id: str = ""
    media: tuple[str, ...] = ()
    received_at: datetime = field(default_factory=_utc_now)
    metadata: Mapping[str, object] = field(default_factory=dict)

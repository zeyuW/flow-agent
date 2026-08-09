"""会话和消息数据模型（规范 1c）。"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class SessionMeta:
    """从 SQLite 会话表读取的会话元数据。"""

    key: str
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    last_consolidated: int = 0
    next_seq: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Session:
    """内存中的会话对象（规范 1c）。

    保存单个会话的完整消息列表和元数据，支持按起始位置、最大消息数和归档游标重建历史。
    """

    key: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    last_consolidated: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

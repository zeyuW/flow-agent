"""会话历史的只读查询服务。"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from application.passive.domain.session_key import split_session_key
from application.passive.infra.session_store import SessionStore


@dataclass(frozen=True, slots=True)
class SessionSummary:
    id: str
    channel: str
    external_conversation_id: str
    created_at: str
    updated_at: str
    message_count: int
    preview: str | None


@dataclass(frozen=True, slots=True)
class SessionMessage:
    role: str
    content: str
    timestamp: str
    tool_chain: list[str]


@dataclass(frozen=True, slots=True)
class SessionDetail(SessionSummary):
    messages: list[SessionMessage]


class SessionQueryService:
    """向接口层提供已持久化会话的只读视图。"""

    def __init__(self, store: SessionStore) -> None:
        self._store = store

    def list_sessions(
        self, start_date: date, end_date: date, limit: int
    ) -> list[SessionSummary]:
        """按服务所在时区的日期范围查询会话摘要。"""

        if start_date > end_date:
            raise ValueError("开始日期不能晚于结束日期")
        start_at = self._day_start(start_date)
        end_at = self._day_start(end_date + timedelta(days=1))
        rows = self._store.list_session_summaries(
            start_at.isoformat(), end_at.isoformat(), max(1, min(limit, 100))
        )
        return [self._summary_from_row(row) for row in rows]

    def get_session(self, session_id: str) -> SessionDetail | None:
        """读取一个会话的用户和 Agent 消息。"""

        meta = self._store.get_session_meta(session_id)
        if meta is None:
            return None
        channel, external_conversation_id = split_session_key(session_id)
        messages = [
            SessionMessage(
                role=message["role"],
                content=message["content"],
                timestamp=message["timestamp"],
                tool_chain=list(message["tool_chain"]),
            )
            for message in self._store.fetch_session_messages(session_id)
            if message["role"] in {"user", "assistant"}
        ]
        return SessionDetail(
            id=session_id,
            channel=channel,
            external_conversation_id=external_conversation_id,
            created_at=meta.created_at.isoformat(),
            updated_at=meta.updated_at.isoformat(),
            message_count=len(messages),
            preview=messages[-1].content if messages else None,
            messages=messages,
        )

    @staticmethod
    def _day_start(day: date) -> datetime:
        local_time = datetime.combine(day, time.min).astimezone()
        return local_time.astimezone(timezone.utc)

    @staticmethod
    def _summary_from_row(row: dict[str, Any]) -> SessionSummary:
        session_id = str(row["key"])
        channel, external_conversation_id = split_session_key(session_id)
        return SessionSummary(
            id=session_id,
            channel=channel,
            external_conversation_id=external_conversation_id,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            message_count=int(row["message_count"]),
            preview=str(row["preview"]) if row["preview"] is not None else None,
        )

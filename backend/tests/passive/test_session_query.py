from datetime import date, datetime, time

import pytest

from application.passive.app.session_query import SessionQueryService
from application.passive.infra.session_store import SessionStore


@pytest.fixture
def store(tmp_path):
    return SessionStore(tmp_path / "sessions.db")


@pytest.fixture
def query_service(store):
    return SessionQueryService(store)


def _local_day_timestamp(day: date, hour: int = 10) -> str:
    local_time = datetime.combine(day, time(hour)).astimezone()
    return local_time.isoformat()


def test_list_sessions_filters_by_local_calendar_date(store, query_service):
    today = date(2026, 8, 21)
    today_timestamp = _local_day_timestamp(today)
    yesterday_timestamp = _local_day_timestamp(date(2026, 8, 20))
    store.upsert_session("telegram:1", updated_at=today_timestamp)
    store.insert_message("telegram:1", 1, "user", "今天的消息", ts=today_timestamp)
    store.upsert_session("qq:2", updated_at=yesterday_timestamp)

    result = query_service.list_sessions(today, today, 50)

    assert [item.id for item in result] == ["telegram:1"]
    assert result[0].channel == "telegram"
    assert result[0].preview == "今天的消息"


def test_get_session_returns_user_and_assistant_messages(store, query_service):
    timestamp = _local_day_timestamp(date(2026, 8, 21))
    store.upsert_session("qq:group:1", updated_at=timestamp)
    store.insert_message("qq:group:1", 1, "user", "你好", ts=timestamp)
    store.insert_message(
        "qq:group:1",
        2,
        "assistant",
        "你好，有什么可以帮你？",
        ["search"],
        ts=timestamp,
    )

    detail = query_service.get_session("qq:group:1")

    assert detail is not None
    assert [(item.role, item.content, item.tool_chain) for item in detail.messages] == [
        ("user", "你好", []),
        ("assistant", "你好，有什么可以帮你？", ["search"]),
    ]


def test_legacy_session_key_uses_legacy_channel(store, query_service):
    timestamp = _local_day_timestamp(date(2026, 8, 21))
    store.upsert_session("old-id", updated_at=timestamp)

    detail = query_service.get_session("old-id")

    assert detail is not None
    assert (detail.channel, detail.external_conversation_id) == ("legacy", "old-id")

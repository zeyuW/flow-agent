from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from application.agent.app.tracing import TraceTimeline
from application.passive.app.session_query import (
    SessionDetail,
    SessionMessage,
    SessionSummary,
)
from infra.bus.event import Event
from interfaces.admin.router import create_admin_app


def _routes():
    timeline = TraceTimeline()
    started = datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)
    for event_type, trace_id, seconds, payload in [
        ("before_turn", "trace-1", 0, {"channel": "telegram", "user_input": "private"}),
        ("tool_call_started", "trace-1", 2, {"tool_args": {"secret": "private"}}),
        ("turn_committed", "trace-1", 4.21, {"assistant_output": "private"}),
        ("before_turn", "trace-2", 60, {"channel": "http"}),
    ]:
        event = Event(event_type, trace_id=trace_id, payload=payload)
        event.timestamp = started + timedelta(seconds=seconds)
        timeline.record(event)
    app = create_admin_app(timeline, _SessionQuery())
    return {route.path: route.endpoint for route in app.routes}


class _SessionQuery:
    def list_sessions(
        self, start_date: date, end_date: date, limit: int
    ) -> list[SessionSummary]:
        return [
            SessionSummary(
                id="telegram:1",
                channel="telegram",
                external_conversation_id="1",
                created_at="2026-08-21T02:00:00+00:00",
                updated_at="2026-08-21T02:00:00+00:00",
                message_count=1,
                preview="你好",
            )
        ]

    def get_session(self, session_id: str) -> SessionDetail | None:
        if session_id == "missing":
            return None
        return SessionDetail(
            id="telegram:1",
            channel="telegram",
            external_conversation_id="1",
            created_at="2026-08-21T02:00:00+00:00",
            updated_at="2026-08-21T02:00:00+00:00",
            message_count=1,
            preview="你好",
            messages=[
                SessionMessage(
                    role="user",
                    content="你好",
                    timestamp="2026-08-21T02:00:00+00:00",
                    tool_chain=[],
                )
            ],
        )


def _routes_with_sessions():
    app = _app_with_sessions()
    return {route.path: route.endpoint for route in app.routes}


def _app_with_sessions():
    return create_admin_app(TraceTimeline(), _SessionQuery())


def test_traces_filters_and_excludes_sensitive_data():
    response = _routes()["/api/traces"](
        limit=20, status="completed", channel="telegram"
    )

    assert response == [
        {
            "id": "trace-1",
            "channel": "telegram",
            "status": "completed",
            "started_at": "2026-08-10T10:00:00Z",
            "duration_ms": 4210,
        }
    ]


def test_trace_detail_and_events_follow_contract():
    routes = _routes()
    detail = routes["/api/traces/{trace_id}"]("trace-1")
    events = routes["/api/events"](limit=20, trace_id=None, type="turn_started")

    assert [item["type"] for item in detail["events"]] == [
        "turn_started",
        "tool_started",
        "turn_committed",
    ]
    assert "private" not in str(detail)
    assert [item["trace_id"] for item in events] == ["trace-2", "trace-1"]


def test_unknown_trace_returns_contract_error():
    routes = _routes()

    with pytest.raises(HTTPException, match="未找到追踪记录: missing"):
        routes["/api/traces/{trace_id}"]("missing")


def test_sessions_routes_return_summaries_and_details():
    routes = _routes_with_sessions()

    summaries = routes["/api/sessions"](
        start_date=date(2026, 8, 21), end_date=date(2026, 8, 21), limit=50
    )
    detail = routes["/api/sessions/{session_id}"]("telegram:1")

    assert summaries[0].channel == "telegram"
    assert detail.messages[0].content == "你好"


def test_unknown_session_returns_404():
    routes = _routes_with_sessions()

    with pytest.raises(HTTPException, match="未找到会话: missing"):
        routes["/api/sessions/{session_id}"]("missing")


def test_sessions_rejects_reversed_date_range():
    client = TestClient(_app_with_sessions())

    response = client.get(
        "/api/sessions",
        params={"start_date": "2026-08-22", "end_date": "2026-08-21"},
    )

    assert response.status_code == 422

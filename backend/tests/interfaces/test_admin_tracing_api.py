from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from application.agent.app.tracing import TraceTimeline
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
    app = create_admin_app(timeline)
    return {route.path: route.endpoint for route in app.routes}


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

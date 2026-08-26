from datetime import datetime, timedelta, timezone

from infra.bus.event import Event


def _event(
    event_type: str,
    *,
    trace_id: str = "trace-1",
    at: datetime,
    payload: dict[str, object] | None = None,
) -> Event:
    event = Event(event_type, trace_id=trace_id, payload=payload)
    event.timestamp = at
    return event


def test_timeline_exposes_only_safe_completed_trace_data():
    from application.agent.app.tracing import TraceTimeline

    started_at = datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)
    timeline = TraceTimeline()
    timeline.record(
        _event(
            "before_turn",
            at=started_at,
            payload={"channel": "telegram", "user_input": "private"},
        )
    )
    timeline.record(
        _event(
            "tool_call_started",
            at=started_at + timedelta(seconds=2),
            payload={"tool_name": "lookup", "tool_args": {"secret": "x"}},
        )
    )
    timeline.record(
        _event(
            "tool_call_completed",
            at=started_at + timedelta(seconds=3),
            payload={"tool_name": "lookup", "result": "private result"},
        )
    )
    timeline.record(
        _event(
            "turn_committed",
            at=started_at + timedelta(milliseconds=4210),
            payload={"assistant_output": "private output"},
        )
    )

    trace = timeline.get_trace("trace-1")

    assert trace is not None
    detail = trace.as_detail()
    assert detail["channel"] == "telegram"
    assert detail["status"] == "completed"
    assert detail["started_at"] == "2026-08-10T10:00:00Z"
    assert detail["finished_at"] == "2026-08-10T10:00:04.210000Z"
    assert detail["duration_ms"] == 4210
    assert [event["type"] for event in detail["events"]] == [
        "turn_started",
        "tool_started",
        "tool_finished",
        "turn_committed",
    ]
    assert all("private" not in event["summary"] for event in detail["events"])
    assert all(event["error"] is None for event in detail["events"])


def test_timeline_filters_and_orders_trace_and_event_queries():
    from application.agent.app.tracing import TraceTimeline

    started_at = datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)
    timeline = TraceTimeline()
    timeline.record(
        _event(
            "before_turn",
            trace_id="trace-1",
            at=started_at,
            payload={"channel": "telegram"},
        )
    )
    timeline.record(
        _event(
            "turn_committed", trace_id="trace-1", at=started_at + timedelta(seconds=1)
        )
    )
    timeline.record(
        _event(
            "before_turn",
            trace_id="trace-2",
            at=started_at + timedelta(seconds=2),
            payload={"channel": "http"},
        )
    )

    traces = timeline.list_traces(limit=20, status="completed", channel="telegram")
    events = timeline.list_events(limit=20, trace_id=None, event_type="turn_started")

    assert [trace.id for trace in traces] == ["trace-1"]
    assert [event.trace_id for event in events] == ["trace-2", "trace-1"]


def test_timeline_ignores_events_without_trace_id():
    from application.agent.app.tracing import TraceTimeline

    timeline = TraceTimeline()
    timeline.record(Event("before_turn", payload={"channel": "telegram"}))

    assert timeline.list_traces(limit=20, status=None, channel=None) == []


def test_timeline_groups_subagent_lifecycle_into_parent_trace():
    from application.agent.app.tracing import TraceTimeline

    timeline = TraceTimeline()
    timeline.record(Event("turn_started", trace_id="trace-parent"))
    timeline.record(
        Event(
            "subagent_started",
            trace_id="trace-parent",
            payload={"job_id": "task-a"},
        )
    )
    timeline.record(
        Event(
            "subagent_completed",
            trace_id="trace-parent",
            payload={"job_id": "task-a"},
        )
    )
    timeline.record(Event("turn_committed", trace_id="trace-parent"))

    record = timeline.get_trace("trace-parent")

    assert record is not None
    assert [event.type for event in record.events] == [
        "turn_started",
        "subagent_started",
        "subagent_completed",
        "turn_committed",
    ]
    assert [event.stage for event in record.events] == [
        "passive",
        "subagent",
        "subagent",
        "passive",
    ]

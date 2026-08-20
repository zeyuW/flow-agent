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
from application.schedule.domain.models import ScheduledTask
from application.schedule.app.runtime import SchedulerService
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
    app = create_admin_app(timeline, _SessionQuery(), _Scheduler())
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

    def get_session(
        self,
        session_id: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> SessionDetail | None:
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
    return create_admin_app(TraceTimeline(), _SessionQuery(), _Scheduler())


class _Scheduler:
    def __init__(self) -> None:
        self.cancelled_id = ""
        self.created: dict[str, str] | None = None
        self.resumed_id = ""

    def list_all_tasks(self) -> list[ScheduledTask]:
        return [
            ScheduledTask(
                id="daily-news",
                name="每日资讯",
                trigger="daily",
                task_type="agent",
                message="整理今天的 AI 新闻",
                channel="telegram",
                session_id="telegram:1",
                chat_id="1",
                timezone="Asia/Shanghai",
                next_run_at=datetime(2026, 8, 22, 0, 30, tzinfo=timezone.utc),
                daily_time="08:30",
                run_count=3,
            )
        ]

    def cancel_task_by_id(self, task_id: str) -> bool:
        self.cancelled_id = task_id
        return task_id == "daily-news"

    def get_task_by_id(self, task_id: str) -> ScheduledTask | None:
        return self.list_all_tasks()[0] if task_id == "daily-news" else None

    def create_task(self, **kwargs: str) -> ScheduledTask:
        self.created = kwargs
        return ScheduledTask(
            id="new-task",
            name=kwargs["name"],
            trigger=kwargs["trigger"],
            task_type=kwargs["task_type"],
            message=kwargs["message"],
            channel=kwargs["channel"],
            session_id=kwargs["session_id"],
            chat_id=kwargs["chat_id"],
            timezone="Asia/Shanghai",
            next_run_at=datetime(2026, 8, 22, 0, 30, tzinfo=timezone.utc),
        )

    def resume_task_by_id(self, task_id: str) -> bool:
        self.resumed_id = task_id
        return task_id == "daily-news"


def _routes_with_schedules():
    scheduler = _Scheduler()
    app = create_admin_app(TraceTimeline(), _SessionQuery(), scheduler)
    return {route.path: route.endpoint for route in app.routes}, scheduler


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


def test_schedules_routes_list_and_cancel_tasks():
    scheduler = _Scheduler()
    client = TestClient(
        create_admin_app(TraceTimeline(), _SessionQuery(), scheduler),
        raise_server_exceptions=False,
    )

    tasks = client.get("/api/schedules")
    result = client.post("/api/schedules/daily-news/cancel")

    assert tasks.status_code == 200
    assert tasks.json()[0]["name"] == "每日资讯"
    assert tasks.json()[0]["channel"] == "telegram"
    assert result.json() == {"cancelled": True}
    assert scheduler.cancelled_id == "daily-news"


def test_cancel_unknown_schedule_returns_404():
    routes, _ = _routes_with_schedules()

    with pytest.raises(HTTPException, match="未找到定时任务: missing"):
        routes["/api/schedules/{task_id}/cancel"]("missing")


def test_schedules_can_create_and_resume_tasks():
    scheduler = _Scheduler()
    client = TestClient(create_admin_app(TraceTimeline(), _SessionQuery(), scheduler))

    created = client.post(
        "/api/schedules",
        json={
            "target_task_id": "daily-news",
            "name": "午间提醒",
            "trigger": "daily",
            "when": "12:30",
            "task_type": "reminder",
            "message": "记得午休",
        },
    )
    resumed = client.post("/api/schedules/daily-news/resume")

    assert created.status_code == 200
    assert created.json()["id"] == "new-task"
    assert scheduler.created == {
        "channel": "telegram",
        "chat_id": "1",
        "message": "记得午休",
        "name": "午间提醒",
        "session_id": "telegram:1",
        "task_type": "reminder",
        "timezone_name": "Asia/Shanghai",
        "trigger": "daily",
        "when": "12:30",
    }
    assert resumed.status_code == 200
    assert scheduler.resumed_id == "daily-news"


def test_schedule_creation_returns_a_validation_error_for_invalid_daily_time(tmp_path):
    scheduler = SchedulerService(store_path=tmp_path / "scheduled.db")
    target = scheduler.create_task(
        trigger="daily",
        when="08:00",
        task_type="agent",
        message="每日新闻",
        channel="telegram",
        session_id="telegram:1",
        chat_id="1",
    )
    client = TestClient(
        create_admin_app(TraceTimeline(), _SessionQuery(), scheduler),
        raise_server_exceptions=False,
    )

    response = client.post(
        "/api/schedules",
        json={
            "target_task_id": target.id,
            "trigger": "daily",
            "when": "24:00",
            "task_type": "agent",
            "message": "睡前讲一个笑话",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "每日任务时间必须使用 HH:MM，例如 08:30"

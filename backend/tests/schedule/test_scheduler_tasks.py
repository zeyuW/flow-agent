from datetime import datetime, timedelta, timezone

from infra.bus.message import InboundQueue
from application.schedule.app.runtime import SchedulerService
from application.schedule.domain.models import parse_duration
from application.schedule.app.tools import (
    CancelScheduledTaskTool,
    ListScheduledTasksTool,
    ScheduleTaskTool,
)
from application.capabilities.tools.registry import ToolRegistry


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class RecordingOutboundPort:
    def __init__(self) -> None:
        self.items = []

    def send(self, dispatch) -> None:
        self.items.append(dispatch)


def test_duration_parser_supports_compound_values():
    assert parse_duration("1d2h3m4s") == timedelta(
        days=1,
        hours=2,
        minutes=3,
        seconds=4,
    )


def test_one_time_reminder_is_persisted_and_sent(tmp_path):
    clock = MutableClock(datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc))
    outbound = RecordingOutboundPort()
    service = SchedulerService(
        store_path=tmp_path / "scheduled.db",
        outbound_port=outbound,
        now_fn=clock,
    )

    task = service.create_task(
        trigger="after",
        when="5m",
        task_type="reminder",
        message="起来活动一下",
        channel="telegram",
        session_id="session-1",
        chat_id="chat-1",
    )

    restored = SchedulerService(
        store_path=tmp_path / "scheduled.db",
        outbound_port=outbound,
        now_fn=clock,
    )
    assert restored.list_tasks("session-1")[0].id == task.id

    clock.value += timedelta(minutes=5)
    assert restored.run_due_once() == 1
    assert outbound.items[0].text == "起来活动一下"
    assert outbound.items[0].chat_id == "chat-1"
    assert restored.list_tasks("session-1") == []


def test_daily_agent_task_reenters_agent_pipeline(tmp_path):
    clock = MutableClock(datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc))
    inbound = InboundQueue()
    service = SchedulerService(
        store_path=tmp_path / "scheduled.db",
        inbound_queue=inbound,
        now_fn=clock,
    )
    task = service.create_task(
        trigger="daily",
        when="16:01",
        task_type="agent",
        message="查询过去24小时AI新闻并推荐10条",
        channel="telegram",
        session_id="session-1",
        chat_id="chat-1",
        timezone_name="Asia/Shanghai",
    )

    clock.value += timedelta(minutes=1)
    assert service.run_due_once() == 1
    message = inbound.consume_one()
    assert message is not None
    assert "查询过去24小时AI新闻" in message.text
    assert message.metadata["scheduled_task_id"] == task.id
    assert message.chat_id == "chat-1"

    remaining = service.list_tasks("session-1")
    assert len(remaining) == 1
    assert remaining[0].next_run_at == datetime(
        2026,
        7,
        20,
        8,
        1,
        tzinfo=timezone.utc,
    )


def test_schedule_tools_scope_tasks_to_current_session(tmp_path):
    clock = MutableClock(datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc))
    service = SchedulerService(
        store_path=tmp_path / "scheduled.db",
        now_fn=clock,
    )
    schedule = ScheduleTaskTool(service)
    listed = ListScheduledTasksTool(service)
    cancel = CancelScheduledTaskTool(service)

    created = schedule.run(
        {
            "trigger": "after",
            "when": "10m",
            "task_type": "reminder",
            "message": "测试提醒",
            "__channel": "telegram",
            "__session_id": "session-1",
            "__chat_id": "chat-1",
        }
    )
    assert created.ok is True
    task_id = service.list_tasks("session-1")[0].id
    assert "测试提醒" in listed.run({"__session_id": "session-1"}).content
    assert cancel.run({"task_id": task_id, "__session_id": "session-2"}).ok is False
    assert cancel.run({"task_id": task_id, "__session_id": "session-1"}).ok is True


def test_admin_can_list_and_cancel_tasks_from_all_sessions(tmp_path):
    service = SchedulerService(store_path=tmp_path / "scheduled.db")
    first = service.create_task(
        trigger="after",
        when="10m",
        task_type="reminder",
        message="第一条提醒",
        channel="telegram",
        session_id="telegram:1",
        chat_id="1",
    )
    second = service.create_task(
        trigger="after",
        when="20m",
        task_type="agent",
        message="第二条任务",
        channel="qq",
        session_id="qq:2",
        chat_id="2",
    )

    assert [task.id for task in service.list_all_tasks()] == [first.id, second.id]
    assert service.cancel_task_by_id(first.id) is True
    assert service.list_all_tasks()[0].enabled is False


def test_admin_can_resume_a_recurring_task(tmp_path):
    clock = MutableClock(datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc))
    service = SchedulerService(store_path=tmp_path / "scheduled.db", now_fn=clock)
    task = service.create_task(
        trigger="daily",
        when="08:30",
        task_type="reminder",
        message="早间提醒",
        channel="telegram",
        session_id="telegram:1",
        chat_id="1",
    )

    assert service.cancel_task_by_id(task.id) is True
    clock.value = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)

    assert service.resume_task_by_id(task.id) is True
    resumed = service.get_task_by_id(task.id)
    assert resumed is not None
    assert resumed.enabled is True
    assert resumed.next_run_at > clock.value


def test_admin_can_resume_an_unexpired_one_time_task(tmp_path):
    clock = MutableClock(datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc))
    service = SchedulerService(store_path=tmp_path / "scheduled.db", now_fn=clock)
    task = service.create_task(
        trigger="after",
        when="10m",
        task_type="reminder",
        message="喝水提醒",
        channel="telegram",
        session_id="telegram:1",
        chat_id="1",
    )

    assert service.cancel_task_by_id(task.id) is True
    assert service.resume_task_by_id(task.id) is True
    resumed = service.get_task_by_id(task.id)
    assert resumed is not None
    assert resumed.enabled is True
    assert resumed.next_run_at == task.next_run_at


def test_admin_can_restart_an_expired_one_time_task_now(tmp_path):
    clock = MutableClock(datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc))
    service = SchedulerService(store_path=tmp_path / "scheduled.db", now_fn=clock)
    task = service.create_task(
        trigger="after",
        when="10m",
        task_type="reminder",
        message="喝水提醒",
        channel="telegram",
        session_id="telegram:1",
        chat_id="1",
    )

    assert service.cancel_task_by_id(task.id) is True
    clock.value = datetime(2026, 7, 19, 9, 0, tzinfo=timezone.utc)

    assert service.resume_task_by_id(task.id) is True
    resumed = service.get_task_by_id(task.id)
    assert resumed is not None
    assert resumed.enabled is True
    assert resumed.next_run_at == clock.value


def test_schedule_tool_is_selected_for_chinese_reminder_request(tmp_path):
    service = SchedulerService(store_path=tmp_path / "scheduled.db")
    registry = ToolRegistry()
    registry.register(ScheduleTaskTool(service))
    registry.register(ListScheduledTasksTool(service))

    selected = registry.select_openai_tools("十分钟后提醒我喝水", max_tools=1)

    assert selected[0]["function"]["name"] == "schedule_task"

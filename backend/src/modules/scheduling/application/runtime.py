"""持久化定时任务服务。"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from modules.conversation.domain.channel_message import InboundMessage
from modules.delivery.infra.message_bus import OutboundDispatch

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "Asia/Shanghai"
_DURATION_RE = re.compile(
    r"^(?:(?P<days>\d+)d)?(?:(?P<hours>\d+)h)?"
    r"(?:(?P<minutes>\d+)m)?(?:(?P<seconds>\d+)s)?$"
)


@dataclass(slots=True)
class ScheduledTask:
    """一条可持久化并恢复执行的用户定时任务。"""

    id: str
    name: str
    trigger: str
    task_type: str
    message: str
    channel: str
    session_id: str
    chat_id: str
    timezone: str
    next_run_at: datetime
    interval_seconds: int | None = None
    daily_time: str | None = None
    enabled: bool = True
    run_count: int = 0
    created_at: datetime | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, object]:
        """转换为工具和日志可安全输出的结构。"""

        return {
            "id": self.id,
            "name": self.name,
            "trigger": self.trigger,
            "task_type": self.task_type,
            "message": self.message,
            "channel": self.channel,
            "session_id": self.session_id,
            "timezone": self.timezone,
            "next_run_at": self.next_run_at.isoformat(),
            "interval_seconds": self.interval_seconds,
            "daily_time": self.daily_time,
            "enabled": self.enabled,
            "run_count": self.run_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_error": self.last_error,
        }


class ScheduledTaskStore:
    """使用 SQLite 保存任务，避免重启或并发写入导致丢失。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    next_run_at TEXT NOT NULL,
                    interval_seconds INTEGER,
                    daily_time TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    run_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    last_error TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_scheduled_due "
                "ON scheduled_tasks(enabled, next_run_at)"
            )

    def add(self, task: ScheduledTask) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO scheduled_tasks (
                    id, name, trigger, task_type, message, channel,
                    session_id, chat_id, timezone, next_run_at,
                    interval_seconds, daily_time, enabled, run_count,
                    created_at, last_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.name,
                    task.trigger,
                    task.task_type,
                    task.message,
                    task.channel,
                    task.session_id,
                    task.chat_id,
                    task.timezone,
                    task.next_run_at.isoformat(),
                    task.interval_seconds,
                    task.daily_time,
                    int(task.enabled),
                    task.run_count,
                    (task.created_at or datetime.now(timezone.utc)).isoformat(),
                    task.last_error,
                ),
            )

    def list_for_session(self, session_id: str, *, include_disabled: bool = False) -> list[ScheduledTask]:
        query = "SELECT * FROM scheduled_tasks WHERE session_id = ?"
        params: list[object] = [session_id]
        if not include_disabled:
            query += " AND enabled = 1"
        query += " ORDER BY next_run_at"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._from_row(row) for row in rows]

    def due(self, now: datetime) -> list[ScheduledTask]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM scheduled_tasks "
                "WHERE enabled = 1 AND next_run_at <= ? ORDER BY next_run_at",
                (now.astimezone(timezone.utc).isoformat(),),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def next_due_at(self) -> datetime | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT next_run_at FROM scheduled_tasks "
                "WHERE enabled = 1 ORDER BY next_run_at LIMIT 1"
            ).fetchone()
        return _parse_datetime(row["next_run_at"]) if row is not None else None

    def cancel(self, task_id: str, session_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE scheduled_tasks SET enabled = 0 "
                "WHERE id = ? AND session_id = ? AND enabled = 1",
                (task_id, session_id),
            )
        return cursor.rowcount > 0

    def complete(self, task: ScheduledTask, *, next_run_at: datetime | None, error: str | None) -> None:
        enabled = next_run_at is not None
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE scheduled_tasks
                SET enabled = ?, next_run_at = ?, run_count = run_count + 1,
                    last_error = ?
                WHERE id = ?
                """,
                (
                    int(enabled),
                    (next_run_at or task.next_run_at).isoformat(),
                    error,
                    task.id,
                ),
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ScheduledTask:
        return ScheduledTask(
            id=str(row["id"]),
            name=str(row["name"]),
            trigger=str(row["trigger"]),
            task_type=str(row["task_type"]),
            message=str(row["message"]),
            channel=str(row["channel"]),
            session_id=str(row["session_id"]),
            chat_id=str(row["chat_id"]),
            timezone=str(row["timezone"]),
            next_run_at=_parse_datetime(str(row["next_run_at"])),
            interval_seconds=row["interval_seconds"],
            daily_time=row["daily_time"],
            enabled=bool(row["enabled"]),
            run_count=int(row["run_count"]),
            created_at=_parse_datetime(str(row["created_at"])),
            last_error=row["last_error"],
        )


class SchedulerService:
    """创建、恢复并到期投递用户提醒和 Agent 任务。"""

    def __init__(
        self,
        *,
        store_path: str | Path,
        inbound_queue=None,
        outbound_port=None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = ScheduledTaskStore(store_path)
        self.inbound_queue = inbound_queue
        self.outbound_port = outbound_port
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def create_task(
        self,
        *,
        trigger: str,
        when: str,
        task_type: str,
        message: str,
        channel: str,
        session_id: str,
        chat_id: str,
        timezone_name: str = DEFAULT_TIMEZONE,
        name: str = "",
    ) -> ScheduledTask:
        """校验触发规则并创建一条持久化任务。"""

        if trigger not in {"after", "at", "daily", "every"}:
            raise ValueError("trigger 必须是 after、at、daily 或 every")
        if task_type not in {"reminder", "agent"}:
            raise ValueError("task_type 必须是 reminder 或 agent")
        if not message.strip():
            raise ValueError("message 不能为空")
        if not session_id or not channel:
            raise ValueError("缺少当前会话上下文")
        tz = _load_timezone(timezone_name)
        now = self._aware_now().astimezone(tz)
        interval_seconds: int | None = None
        daily_time: str | None = None
        if trigger == "after":
            next_run = now + parse_duration(when)
        elif trigger == "at":
            next_run = parse_at(when, tz, now)
        elif trigger == "daily":
            daily_time = normalize_clock_time(when)
            next_run = parse_at(daily_time, tz, now)
        else:
            interval = parse_duration(when)
            interval_seconds = int(interval.total_seconds())
            if interval_seconds < 1:
                raise ValueError("周期必须至少为 1 秒")
            next_run = now + interval
        task = ScheduledTask(
            id=uuid4().hex[:12],
            name=name.strip() or message.strip()[:40],
            trigger=trigger,
            task_type=task_type,
            message=message.strip(),
            channel=channel,
            session_id=session_id,
            chat_id=chat_id or session_id,
            timezone=timezone_name,
            next_run_at=next_run.astimezone(timezone.utc),
            interval_seconds=interval_seconds,
            daily_time=daily_time,
            created_at=self._aware_now(),
        )
        self.store.add(task)
        self._wake.set()
        logger.info(
            "定时任务已创建: id=%s trigger=%s next_run_at=%s type=%s",
            task.id,
            task.trigger,
            task.next_run_at.isoformat(),
            task.task_type,
        )
        return task

    def list_tasks(self, session_id: str) -> list[ScheduledTask]:
        return self.store.list_for_session(session_id)

    def cancel_task(self, task_id: str, session_id: str) -> bool:
        cancelled = self.store.cancel(task_id, session_id)
        if cancelled:
            self._wake.set()
        return cancelled

    def start(self) -> None:
        """启动唯一的后台调度线程。"""

        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._wake.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="scheduled-task-runtime",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """停止调度线程并等待当前轮结束。"""

        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def run_due_once(self) -> int:
        """执行当前全部到期任务，供后台循环和测试复用。"""

        now = self._aware_now()
        tasks = self.store.due(now)
        for task in tasks:
            error: str | None = None
            try:
                self._dispatch(task)
            except Exception as exc:
                error = str(exc)
                logger.exception("定时任务投递失败: id=%s", task.id)
            next_run = self._next_run(task, now, failed=error is not None)
            self.store.complete(task, next_run_at=next_run, error=error)
        return len(tasks)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            self.run_due_once()
            due_at = self.store.next_due_at()
            if due_at is None:
                timeout = 30.0
            else:
                timeout = max(
                    0.1,
                    min(30.0, (due_at - self._aware_now()).total_seconds()),
                )
            self._wake.wait(timeout)
            self._wake.clear()

    def _dispatch(self, task: ScheduledTask) -> None:
        if task.task_type == "agent":
            if self.inbound_queue is None:
                raise RuntimeError("Agent 入站队列未配置")
            self.inbound_queue.publish(
                InboundMessage(
                    channel=task.channel,
                    session_id=task.session_id,
                    text=(
                        "[系统定时任务已到期；这是执行指令，不要再次安排任务]\n"
                        f"任务：{task.message}"
                    ),
                    metadata={
                        "scheduled_task": True,
                        "scheduled_task_id": task.id,
                        "telegram_chat_id": task.chat_id,
                    },
                )
            )
            return
        if self.outbound_port is None:
            raise RuntimeError("出站消息端口未配置")
        metadata: dict[str, object] = {
            "scheduled_task": True,
            "scheduled_task_id": task.id,
            "proactive": True,
        }
        if task.channel == "telegram":
            metadata["telegram_chat_id"] = task.chat_id
        self.outbound_port.send(
            OutboundDispatch(
                channel=task.channel,
                session_id=task.session_id,
                text=task.message,
                chat_id=task.chat_id,
                metadata=metadata,
            )
        )

    def _next_run(
        self,
        task: ScheduledTask,
        now: datetime,
        *,
        failed: bool,
    ) -> datetime | None:
        if failed:
            return now + timedelta(seconds=60)
        if task.trigger == "daily" and task.daily_time:
            tz = _load_timezone(task.timezone)
            return parse_at(task.daily_time, tz, now.astimezone(tz)).astimezone(
                timezone.utc
            )
        if task.trigger == "every" and task.interval_seconds:
            next_run = task.next_run_at
            interval = timedelta(seconds=task.interval_seconds)
            while next_run <= now:
                next_run += interval
            return next_run
        return None

    def _aware_now(self) -> datetime:
        value = self._now_fn()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def parse_duration(value: str) -> timedelta:
    """解析 30s、5m、2h、1d2h 等紧凑时长。"""

    match = _DURATION_RE.fullmatch(value.strip().lower())
    if match is None or not any(match.groupdict().values()):
        raise ValueError("无效时长，示例：30s、5m、2h、1d2h")
    parts = {name: int(raw or 0) for name, raw in match.groupdict().items()}
    duration = timedelta(**parts)
    if duration.total_seconds() <= 0:
        raise ValueError("时长必须大于 0")
    return duration


def normalize_clock_time(value: str) -> str:
    """校验并规范 HH:MM 时刻。"""

    try:
        parsed = datetime.strptime(value.strip(), "%H:%M")
    except ValueError as exc:
        raise ValueError("每日任务时间必须使用 HH:MM，例如 08:30") from exc
    return parsed.strftime("%H:%M")


def parse_at(value: str, tz: ZoneInfo, now: datetime) -> datetime:
    """解析下一次本地时刻或带日期的 ISO 8601 时间。"""

    clean = value.strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", clean):
        clock = datetime.strptime(clean, "%H:%M").time()
        result = now.replace(
            hour=clock.hour,
            minute=clock.minute,
            second=0,
            microsecond=0,
        )
        if result <= now:
            result += timedelta(days=1)
        return result
    try:
        result = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("无法解析时间，请使用 HH:MM 或 ISO 8601") from exc
    if result.tzinfo is None:
        result = result.replace(tzinfo=tz)
    result = result.astimezone(tz)
    if result <= now:
        raise ValueError("指定时间必须晚于当前时间")
    return result


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"无效时区: {name}") from exc

"""定时任务 SQLite 持久化实现。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from application.schedule.domain.models import ScheduledTask


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
            connection.execute("""
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
                """)
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

    def list_for_session(
        self, session_id: str, *, include_disabled: bool = False
    ) -> list[ScheduledTask]:
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

    def complete(
        self, task: ScheduledTask, *, next_run_at: datetime | None, error: str | None
    ) -> None:
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


def _parse_datetime(value: str) -> datetime:
    """把 SQLite 中的时间文本恢复为带 UTC 时区的时间。"""

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

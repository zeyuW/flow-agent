import sqlite3
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class JobRun:
    job_name: str
    ok: bool
    run_id: str = field(default_factory=lambda: uuid4().hex)
    status: str = "running"
    started_at: datetime = field(default_factory=_utc_now)
    finished_at: datetime | None = None
    attempts: int = 1
    error: str | None = None
    result: str | None = None


class InMemoryJobStore:
    """在内存中保存最近的后台任务运行历史。"""

    def __init__(self, capacity: int = 200) -> None:
        self._lock = threading.Lock()
        self._runs: deque[JobRun] = deque(maxlen=max(10, capacity))

    def append(self, run: JobRun) -> None:
        with self._lock:
            self._runs.append(run)

    def list_runs(self) -> list[JobRun]:
        with self._lock:
            return list(self._runs)


class SQLiteJobStore:
    """把后台任务状态和运行历史持久化到 SQLite。"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self._path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS background_job_runs ("
            "run_id TEXT PRIMARY KEY, job_name TEXT NOT NULL, status TEXT NOT NULL, "
            "ok INTEGER NOT NULL, attempts INTEGER NOT NULL, result TEXT, error TEXT, "
            "started_at TEXT NOT NULL, finished_at TEXT)"
        )
        self._db.commit()

    def append(self, run: JobRun) -> None:
        """按 run_id 原子写入或更新任务状态。"""

        with self._lock:
            self._db.execute(
                "INSERT INTO background_job_runs "
                "(run_id, job_name, status, ok, attempts, result, error, started_at, finished_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET "
                "status=excluded.status, ok=excluded.ok, attempts=excluded.attempts, "
                "result=excluded.result, error=excluded.error, finished_at=excluded.finished_at",
                (
                    run.run_id,
                    run.job_name,
                    run.status,
                    int(run.ok),
                    run.attempts,
                    run.result,
                    run.error,
                    run.started_at.isoformat(),
                    run.finished_at.isoformat() if run.finished_at else None,
                ),
            )
            self._db.commit()

    def list_runs(self, limit: int = 200) -> list[JobRun]:
        """按开始时间返回最近的后台任务运行记录。"""

        with self._lock:
            rows = self._db.execute(
                "SELECT run_id, job_name, status, ok, attempts, result, error, "
                "started_at, finished_at FROM background_job_runs "
                "ORDER BY started_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [
            JobRun(
                run_id=str(row[0]),
                job_name=str(row[1]),
                status=str(row[2]),
                ok=bool(row[3]),
                attempts=int(row[4]),
                result=row[5],
                error=row[6],
                started_at=datetime.fromisoformat(str(row[7])),
                finished_at=(
                    datetime.fromisoformat(str(row[8])) if row[8] else None
                ),
            )
            for row in rows
        ]

    def close(self) -> None:
        """关闭数据库连接。"""

        with self._lock:
            self._db.close()

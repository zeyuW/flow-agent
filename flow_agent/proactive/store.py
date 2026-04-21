import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProactiveSentStore(Protocol):
    def was_sent_recently(self, key: str, ttl_seconds: int) -> bool:
        ...

    def mark_sent(self, key: str) -> None:
        ...

    def get_last_sent_at(self) -> datetime | None:
        ...


class SQLiteProactiveSentStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS proactive_sent (
                    key TEXT PRIMARY KEY,
                    sent_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS proactive_meta (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_sent_at TEXT
                )
                """
            )

    def was_sent_recently(self, key: str, ttl_seconds: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT sent_at FROM proactive_sent WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return False
        sent_at = datetime.fromisoformat(row[0])
        return sent_at >= (_utc_now() - timedelta(seconds=ttl_seconds))

    def mark_sent(self, key: str) -> None:
        now_iso = _utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO proactive_sent(key, sent_at)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET sent_at=excluded.sent_at
                """,
                (key, now_iso),
            )
            conn.execute(
                """
                INSERT INTO proactive_meta(id, last_sent_at)
                VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET last_sent_at=excluded.last_sent_at
                """,
                (now_iso,),
            )

    def get_last_sent_at(self) -> datetime | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT last_sent_at FROM proactive_meta WHERE id = 1",
            ).fetchone()
        if row is None or row[0] is None:
            return None
        return datetime.fromisoformat(row[0])

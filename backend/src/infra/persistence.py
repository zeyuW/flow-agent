"""共享 SQLite 持久化基础设施。

本模块集中提供 SQLite 连接、事务边界和可靠出站消息存储。业务模块应在
自己的 ``application/<feature>/infra`` 层定义业务仓储。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
import json
from pathlib import Path
from threading import RLock
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterator


class SQLiteDatabase:
    """提供线程安全的 SQLite 连接和显式事务。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            str(self.path),
            check_same_thread=False,
        )
        self._lock = RLock()
        self._closed = False

    @property
    def connection(self) -> sqlite3.Connection:
        """返回连接对象，供仓储执行查询或配置连接。"""

        if self._closed:
            raise RuntimeError("SQLite 数据库连接已经关闭")
        return self._connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """开启事务，成功提交，异常回滚并继续抛出。"""

        with self._lock:
            connection = self.connection
            connection.execute("BEGIN")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def close(self) -> None:
        """关闭连接；重复关闭不会产生副作用。"""

        with self._lock:
            if self._closed:
                return
            self._connection.close()
            self._closed = True

    def __enter__(self) -> "SQLiteDatabase":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


@dataclass(slots=True, frozen=True)
class OutboxRecord:
    """一条可恢复的出站消息记录。"""

    delivery_id: str
    channel: str
    session_id: str
    chat_id: str
    text: str
    metadata: dict[str, object]
    status: str
    attempts: int
    last_error: str
    created_at: float
    updated_at: float


class SQLiteOutboxStore:
    """使用 SQLite 保存待投递消息及其终态。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._database = SQLiteDatabase(path)
        self._database.connection.row_factory = sqlite3.Row
        self._initialize()

    @property
    def database(self) -> SQLiteDatabase:
        """返回共享 SQLite 适配器。"""

        return self._database

    def _initialize(self) -> None:
        self._database.connection.execute("PRAGMA journal_mode=WAL")
        with self._lock, self._database.transaction() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS outbound_deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    channel TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """)
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_outbound_status_created "
                "ON outbound_deliveries(status, created_at)"
            )

    def mark_interrupted_sending_unknown(self) -> int:
        """启动恢复时把遗留 sending 转为不可自动重放的 unknown。"""

        with self._lock, self._database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE outbound_deliveries
                SET status = 'unknown',
                    last_error = 'process stopped while sending',
                    updated_at = ?
                WHERE status = 'sending'
                """,
                (time.time(),),
            )
        return int(cursor.rowcount)

    def prepare(
        self,
        *,
        delivery_id: str,
        channel: str,
        session_id: str,
        chat_id: str,
        text: str,
        metadata: dict[str, object],
    ) -> None:
        """幂等写入 prepared 状态，不覆盖已经送达的记录。"""

        now = time.time()
        encoded = json.dumps(metadata, ensure_ascii=False, default=str)
        with self._lock, self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO outbound_deliveries (
                    delivery_id, channel, session_id, chat_id, text,
                    metadata_json, status, attempts, last_error,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'prepared', 0, '', ?, ?)
                ON CONFLICT(delivery_id) DO NOTHING
                """,
                (
                    delivery_id,
                    channel,
                    session_id,
                    chat_id,
                    text,
                    encoded,
                    now,
                    now,
                ),
            )

    def mark_sending(self, delivery_id: str) -> None:
        """增加尝试次数并进入 sending 状态。"""

        with self._lock, self._database.transaction() as connection:
            connection.execute(
                """
                UPDATE outbound_deliveries
                SET status = 'sending', attempts = attempts + 1,
                    last_error = '', updated_at = ?
                WHERE delivery_id = ? AND status != 'delivered'
                """,
                (time.time(), delivery_id),
            )

    def mark_delivered(self, delivery_id: str) -> None:
        """提交 delivered 终态。"""

        self._mark_terminal(delivery_id, "delivered", "")

    def mark_failed(self, delivery_id: str, error: str) -> None:
        """记录可在重启后恢复的失败状态。"""

        self._mark_terminal(delivery_id, "failed", error)

    def mark_unknown(self, delivery_id: str, error: str) -> None:
        """记录平台结果不确定且不得自动重放的状态。"""

        self._mark_terminal(delivery_id, "unknown", error)

    def expire_before(self, cutoff: float) -> int:
        """将恢复窗口之前的消息标记为过期，避免启动时补发旧消息。"""

        with self._lock, self._database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE outbound_deliveries
                SET status = 'expired',
                    last_error = 'outbound recovery window expired',
                    updated_at = ?
                WHERE status IN ('prepared', 'failed')
                  AND created_at < ?
                """,
                (time.time(), cutoff),
            )
        return int(cursor.rowcount)

    def mark_expired(
        self,
        delivery_id: str,
        error: str = "outbound retry window expired",
    ) -> None:
        """只将指定出站消息标记为过期，避免影响其他待处理消息。"""

        self._mark_terminal(delivery_id, "expired", error)

    def _mark_terminal(self, delivery_id: str, status: str, error: str) -> None:
        with self._lock, self._database.transaction() as connection:
            connection.execute(
                """
                UPDATE outbound_deliveries
                SET status = ?, last_error = ?, updated_at = ?
                WHERE delivery_id = ?
                """,
                (status, error[:1000], time.time(), delivery_id),
            )

    def list_recoverable(
        self,
        limit: int = 1000,
        *,
        max_age_seconds: float | None = None,
        now: float | None = None,
    ) -> list[OutboxRecord]:
        """按创建顺序读取恢复窗口内的未确认送达消息。"""

        cutoff = None
        if max_age_seconds is not None:
            cutoff = (time.time() if now is None else now) - max(0.0, max_age_seconds)

        with self._lock, self._database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT delivery_id, channel, session_id, chat_id, text,
                       metadata_json, status, attempts, last_error,
                       created_at, updated_at
                FROM outbound_deliveries
                WHERE status IN ('prepared', 'sending', 'failed')
                  AND attempts < 10
                  AND (? IS NULL OR created_at >= ?)
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (cutoff, cutoff, max(1, int(limit))),
            ).fetchall()
        return [self._record_from_row(row) for row in rows]

    def get(self, delivery_id: str) -> OutboxRecord | None:
        """读取单条投递记录，供测试和诊断使用。"""

        with self._lock, self._database.transaction() as connection:
            row = connection.execute(
                """
                SELECT delivery_id, channel, session_id, chat_id, text,
                       metadata_json, status, attempts, last_error,
                       created_at, updated_at
                FROM outbound_deliveries WHERE delivery_id = ?
                """,
                (delivery_id,),
            ).fetchone()
        return self._record_from_row(row) if row is not None else None

    def close(self) -> None:
        """关闭底层数据库连接。"""

        with self._lock:
            self._database.close()

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> OutboxRecord:
        """把数据库行转换成只读记录。"""

        raw_metadata: Any = json.loads(row["metadata_json"])
        return OutboxRecord(
            delivery_id=str(row["delivery_id"]),
            channel=str(row["channel"]),
            session_id=str(row["session_id"]),
            chat_id=str(row["chat_id"]),
            text=str(row["text"]),
            metadata=raw_metadata if isinstance(raw_metadata, dict) else {},
            status=str(row["status"]),
            attempts=int(row["attempts"]),
            last_error=str(row["last_error"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

"""会话和消息的 SQLite 持久化实现（规范 2c、4c、5b）。

包含以下职责：
- 2c：使用 `{session_key}:{seq}` 生成稳定消息 ID；
- 4c：更新 last_consolidated 归档游标；
- 5b：通过原子事务删除消息并更新归档游标。
"""

import json
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from application.passive.domain.session import SessionMeta

logger = logging.getLogger(__name__)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    """基于 SQLite 的会话和消息存储。

    数据表：
    - sessions：key、created_at、updated_at、last_consolidated、next_seq、metadata_json；
    - messages_v2：id（TEXT 主键）、session_key、seq、role、content、tool_chain、extra、ts。
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = None  # 延迟初始化，实际使用 threading.Lock
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        """如果数据表不存在则创建会话表和消息表。"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    key TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_consolidated INTEGER NOT NULL DEFAULT 0,
                    next_seq INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages_v2 (
                    id TEXT PRIMARY KEY,
                    session_key TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tool_chain TEXT NOT NULL DEFAULT '[]',
                    extra TEXT NOT NULL DEFAULT '{}',
                    ts TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_v2_session_key_seq
                ON messages_v2(session_key, seq)
            """)

    # ── 会话元数据 ──

    def get_session_meta(self, key: str) -> SessionMeta | None:
        """从 sessions 表读取会话元数据（规范 1b）。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT key, created_at, updated_at, last_consolidated, next_seq, metadata_json "
                "FROM sessions WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return SessionMeta(
            key=row["key"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_consolidated=row["last_consolidated"],
            next_seq=row["next_seq"],
            metadata=json.loads(row["metadata_json"]),
        )

    def upsert_session(
        self,
        key: str,
        created_at: str = "",
        updated_at: str = "",
        last_consolidated: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """插入或更新会话元数据（规范 2d）。"""
        now = _utc_iso()
        ca = created_at or now
        ua = updated_at or now
        md_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (key, created_at, updated_at, last_consolidated, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    last_consolidated = excluded.last_consolidated,
                    metadata_json = excluded.metadata_json
                """,
                (key, ca, ua, last_consolidated, md_json),
            )

    def update_last_consolidated(self, key: str, last_consolidated: int) -> None:
        """归档完成后更新归档游标（规范 4c）。"""
        now = _utc_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET last_consolidated = ?, updated_at = ? WHERE key = ?",
                (last_consolidated, now, key),
            )

    def list_session_summaries(
        self, start_at: str, end_at: str, limit: int
    ) -> list[dict[str, Any]]:
        """按更新时间读取有限数量的会话摘要。"""

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    sessions.key,
                    sessions.created_at,
                    sessions.updated_at,
                    COUNT(messages_v2.id) AS message_count,
                    (
                        SELECT content
                        FROM messages_v2 AS latest_message
                        WHERE latest_message.session_key = sessions.key
                        ORDER BY latest_message.seq DESC
                        LIMIT 1
                    ) AS preview
                FROM sessions
                LEFT JOIN messages_v2 ON messages_v2.session_key = sessions.key
                WHERE datetime(sessions.updated_at) >= datetime(?)
                  AND datetime(sessions.updated_at) < datetime(?)
                GROUP BY sessions.key
                ORDER BY datetime(sessions.updated_at) DESC
                LIMIT ?
                """,
                (start_at, end_at, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    # ── 消息 ──

    def fetch_session_messages(self, key: str) -> list[dict[str, Any]]:
        """按 seq 顺序读取会话的全部消息（规范 1b）。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, seq, role, content, tool_chain, extra, ts "
                "FROM messages_v2 WHERE session_key = ? ORDER BY seq ASC",
                (key,),
            ).fetchall()
        messages: list[dict[str, Any]] = []
        for row in rows:
            messages.append({
                "id": row["id"],
                "seq": row["seq"],
                "role": row["role"],
                "content": row["content"],
                "tool_chain": json.loads(row["tool_chain"]),
                "extra": json.loads(row["extra"]),
                "timestamp": row["ts"],
                "session_key": key,
            })
        return messages

    def insert_message(
        self,
        session_key: str,
        seq: int,
        role: str,
        content: str,
        tool_chain: list | None = None,
        extra: dict | None = None,
        ts: str = "",
    ) -> str:
        """写入单条消息，并使用 `{session_key}:{seq}` 生成稳定 ID（规范 2c）。

        返回生成的消息 ID。
        """
        msg_id = f"{session_key}:{seq}"
        tc_json = json.dumps(tool_chain or [], ensure_ascii=False)
        ex_json = json.dumps(extra or {}, ensure_ascii=False)
        ts_val = ts or _utc_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO messages_v2 (id, session_key, seq, role, content, tool_chain, extra, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (msg_id, session_key, seq, role, content, tc_json, ex_json, ts_val),
            )
        return msg_id


    def insert_turn(
        self,
        session_key: str,
        user_content: str,
        assistant_content: str,
        *,
        user_extra: dict[str, Any] | None = None,
        assistant_extra: dict[str, Any] | None = None,
        user_tool_chain: list | None = None,
        assistant_tool_chain: list | None = None,
    ) -> list[dict[str, Any]]:
        """在单个事务中写入一轮用户消息和助手消息。"""

        now = _utc_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute(
                    "SELECT next_seq FROM sessions WHERE key = ?",
                    (session_key,),
                ).fetchone()
                if row is None:
                    first_seq = 1
                    conn.execute(
                        "INSERT INTO sessions "
                        "(key, created_at, updated_at, last_consolidated, next_seq, metadata_json) "
                        "VALUES (?, ?, ?, 0, 1, '{}')",
                        (session_key, now, now),
                    )
                else:
                    first_seq = int(row["next_seq"])

                values = [
                    (
                        first_seq,
                        "user",
                        user_content,
                        user_tool_chain or [],
                        user_extra or {},
                    ),
                    (
                        first_seq + 1,
                        "assistant",
                        assistant_content,
                        assistant_tool_chain or [],
                        assistant_extra or {},
                    ),
                ]
                messages: list[dict[str, Any]] = []
                for seq, role, content, tool_chain, extra in values:
                    message_id = f"{session_key}:{seq}"
                    conn.execute(
                        "INSERT INTO messages_v2 "
                        "(id, session_key, seq, role, content, tool_chain, extra, ts) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            message_id,
                            session_key,
                            seq,
                            role,
                            content,
                            json.dumps(tool_chain, ensure_ascii=False),
                            json.dumps(extra, ensure_ascii=False),
                            now,
                        ),
                    )
                    messages.append(
                        {
                            "id": message_id,
                            "session_key": session_key,
                            "seq": seq,
                            "role": role,
                            "content": content,
                            "tool_chain": tool_chain,
                            "extra": extra,
                            "timestamp": now,
                        }
                    )
                conn.execute(
                    "UPDATE sessions SET next_seq = ?, updated_at = ? WHERE key = ?",
                    (first_seq + 2, now, session_key),
                )
                conn.commit()
                return messages
            except Exception:
                conn.rollback()
                raise

    def get_next_seq(self, key: str) -> int:
        """读取并递增会话的 next_seq 计数器。"""
        import threading
        if self._lock is None:
            self._lock = threading.Lock()
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT next_seq FROM sessions WHERE key = ?", (key,)
                ).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO sessions (key, created_at, updated_at) VALUES (?, ?, ?)",
                        (key, _utc_iso(), _utc_iso()),
                    )
                    current = 1
                else:
                    current = row["next_seq"]
                conn.execute(
                    "UPDATE sessions SET next_seq = next_seq + 1 WHERE key = ?", (key,)
                )
        return current

    # ── 撤销（规范 5b） ──

    def delete_session_messages_and_update_cursor(
        self,
        session_key: str,
        ids: list[str],
        last_consolidated: int,
    ) -> int:
        """通过原子事务删除消息并回滚归档游标（规范 5b-5d）。

        参数：
            session_key：会话键；
            ids：待删除的消息 ID；
            last_consolidated：回滚后的新归档游标。

        返回：
            删除的消息数量。
        """
        if not ids:
            return 0

        placeholders = ",".join("?" for _ in ids)
        now = _utc_iso()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                # 5c：查询待删除消息的 seq 编号
                seq_rows = conn.execute(
                    f"SELECT seq FROM messages_v2 WHERE session_key = ? AND id IN ({placeholders})",
                    [session_key] + ids,
                ).fetchall()
                deleted_seqs = [r["seq"] for r in seq_rows]

                # 5b：删除消息
                cursor = conn.execute(
                    f"DELETE FROM messages_v2 WHERE session_key = ? AND id IN ({placeholders})",
                    [session_key] + ids,
                )
                deleted_count = cursor.rowcount

                # 5d：回滚 last_consolidated 并修正 next_seq
                min_seq = min(deleted_seqs) if deleted_seqs else None
                conn.execute(
                    """
                    UPDATE sessions
                    SET last_consolidated = ?,
                        updated_at = ?
                    WHERE key = ?
                    """,
                    (last_consolidated, now, session_key),
                )
                if min_seq is not None:
                    conn.execute(
                        """
                        UPDATE sessions
                        SET next_seq = CASE WHEN next_seq > ? THEN ? ELSE next_seq END
                        WHERE key = ?
                        """,
                        (min_seq, min_seq, session_key),
                    )

                conn.execute("COMMIT")
                return deleted_count
            except Exception:
                conn.execute("ROLLBACK")
                raise

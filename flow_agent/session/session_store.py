"""SessionStore: SQLite persistence for sessions and messages (spec 2c, 4c, 5b).

Implements:
- 2c: insert_message() with {session_key}:{seq} stable id
- 4c: update_last_consolidated()
- 5b: delete_session_messages_and_update_cursor() with atomic transaction
"""

import json
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flow_agent.session.session_models import SessionMeta

logger = logging.getLogger(__name__)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    """SQLite-backed session and message store.

    Tables:
    - sessions: key, created_at, updated_at, last_consolidated, next_seq, metadata_json
    - messages: id (TEXT PK), session_key, seq, role, content, tool_chain, extra, ts
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = None  # initialized lazily — use threading.Lock
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        """Create sessions and messages tables if not exist."""
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
                CREATE TABLE IF NOT EXISTS messages (
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
                CREATE INDEX IF NOT EXISTS idx_messages_session_key_seq
                ON messages(session_key, seq)
            """)

    # ── Session meta ──

    def get_session_meta(self, key: str) -> SessionMeta | None:
        """Read session metadata from sessions table (spec 1b)."""
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
        """Insert or update session metadata (spec 2d)."""
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
        """Update consolidation cursor after consolidation (spec 4c)."""
        now = _utc_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET last_consolidated = ?, updated_at = ? WHERE key = ?",
                (last_consolidated, now, key),
            )

    # ── Messages ──

    def fetch_session_messages(self, key: str) -> list[dict[str, Any]]:
        """Fetch all messages for a session ordered by seq (spec 1b)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, seq, role, content, tool_chain, extra, ts "
                "FROM messages WHERE session_key = ? ORDER BY seq ASC",
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
        """Insert a single message with stable id {session_key}:{seq} (spec 2c).

        Returns the generated message id.
        """
        msg_id = f"{session_key}:{seq}"
        tc_json = json.dumps(tool_chain or [], ensure_ascii=False)
        ex_json = json.dumps(extra or {}, ensure_ascii=False)
        ts_val = ts or _utc_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO messages (id, session_key, seq, role, content, tool_chain, extra, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (msg_id, session_key, seq, role, content, tc_json, ex_json, ts_val),
            )
        return msg_id

    def get_next_seq(self, key: str) -> int:
        """Get and increment the next_seq counter for a session."""
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

    # ── Undo (spec 5b) ──

    def delete_session_messages_and_update_cursor(
        self,
        session_key: str,
        ids: list[str],
        last_consolidated: int,
    ) -> int:
        """Atomic delete messages and rollback cursor (spec 5b-5d).

        Args:
            session_key: Session key.
            ids: Message ids to delete.
            last_consolidated: New last_consolidated value (rolled back).

        Returns:
            Number of messages deleted.
        """
        if not ids:
            return 0

        placeholders = ",".join("?" for _ in ids)
        now = _utc_iso()

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                # 5c: Query seq numbers of deleted messages
                seq_rows = conn.execute(
                    f"SELECT seq FROM messages WHERE session_key = ? AND id IN ({placeholders})",
                    [session_key] + ids,
                ).fetchall()
                deleted_seqs = [r["seq"] for r in seq_rows]

                # 5b: Delete messages
                cursor = conn.execute(
                    f"DELETE FROM messages WHERE session_key = ? AND id IN ({placeholders})",
                    [session_key] + ids,
                )
                deleted_count = cursor.rowcount

                # 5d: Rollback last_consolidated and fix next_seq
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

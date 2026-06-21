import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


@dataclass(slots=True)
class PersistenceManager:
    """Unified schema init/migration/retention/check for SQLite stores."""

    db_path: Path

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    version INTEGER NOT NULL
                )
                """
            )
            row = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
            current_version = int(row[0]) if row else 0
            target_version = 1
            if current_version < 1:
                self._migrate_to_v1(conn)
                conn.execute(
                    "INSERT INTO schema_version(id, version) VALUES(1, ?) ON CONFLICT(id) DO UPDATE SET version=excluded.version",
                    (target_version,),
                )

    def cleanup_retention(self, *, keep_days: int = 30) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, keep_days))).isoformat()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM messages WHERE created_at < ?",
                (cutoff,),
            )
            conn.execute(
                "DELETE FROM proactive_sent WHERE sent_at < ?",
                (cutoff,),
            )

    def consistency_check(self) -> dict[str, int]:
        with self._connect() as conn:
            messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()
            sent = conn.execute("SELECT COUNT(*) FROM proactive_sent").fetchone()
        return {
            "messages": int(messages[0] if messages else 0),
            "proactive_sent": int(sent[0] if sent else 0),
        }

    def _migrate_to_v1(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_messages_session_id_id
            ON messages(session_id, id)
            """
        )
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                embedding_json TEXT,
                content_hash TEXT NOT NULL,
                reinforcement INTEGER NOT NULL DEFAULT 1,
                emotional_weight REAL NOT NULL DEFAULT 1.0,
                status TEXT NOT NULL DEFAULT 'active',
                source_ref TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_content_hash_type
            ON memory_items(content_hash, memory_type)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memory_status
            ON memory_items(status)
            """
        )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)


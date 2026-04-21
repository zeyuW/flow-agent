import sqlite3
from pathlib import Path
from typing import Protocol


class MessageStore(Protocol):
    def list_messages(self, session_id: str) -> list[dict[str, str]]:
        ...

    def append_message(self, session_id: str, role: str, content: str) -> None:
        ...

    def replace_messages(self, session_id: str, messages: list[dict[str, str]]) -> None:
        ...


class InMemoryMessageStore:
    def __init__(self) -> None:
        self._messages_by_session: dict[str, list[dict[str, str]]] = {}

    def list_messages(self, session_id: str) -> list[dict[str, str]]:
        return list(self._messages_by_session.get(session_id, []))

    def append_message(self, session_id: str, role: str, content: str) -> None:
        bucket = self._messages_by_session.setdefault(session_id, [])
        bucket.append({"role": role, "content": content})

    def replace_messages(self, session_id: str, messages: list[dict[str, str]]) -> None:
        self._messages_by_session[session_id] = list(messages)


class SQLiteMessageStore:
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

    def list_messages(self, session_id: str) -> list[dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content
                FROM messages
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()
        return [{"role": row[0], "content": row[1]} for row in rows]

    def append_message(self, session_id: str, role: str, content: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO messages (session_id, role, content)
                VALUES (?, ?, ?)
                """,
                (session_id, role, content),
            )

    def replace_messages(self, session_id: str, messages: list[dict[str, str]]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM messages
                WHERE session_id = ?
                """,
                (session_id,),
            )
            conn.executemany(
                """
                INSERT INTO messages (session_id, role, content)
                VALUES (?, ?, ?)
                """,
                [
                    (session_id, msg.get("role", ""), msg.get("content", ""))
                    for msg in messages
                ],
            )

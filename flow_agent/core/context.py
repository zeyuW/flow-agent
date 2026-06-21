"""Conversation context with session support (spec 4d).

Supports two modes:
- Legacy: ConversationContext(store=MessageStore) — old in-memory/SQLite store
- Session: ConversationContext(db_path=Path) — new SessionManager-backed storage
"""

from pathlib import Path
from typing import Optional

from flow_agent.memory.store import InMemoryMessageStore, MessageStore
from flow_agent.session.session_manager import SessionManager
from flow_agent.session.session_store import SessionStore
from flow_agent.session.session_models import Session
from flow_agent.session.history_builder import get_history


class ConversationContext:
    """Conversation context backed by either MessageStore (legacy) or SessionManager.

    Provides history access via get_history() with optional consolidation cursor,
    message append, multi-session support, and undo.
    """

    def __init__(
        self,
        store: Optional[MessageStore] = None,
        db_path: Optional[Path] = None,
        session_key: str = "default",
    ) -> None:
        self.session_key = session_key
        self._store: MessageStore | None = store
        self._manager: SessionManager | None = None
        self._session: Session | None = None

        # Default to in-memory store if neither store nor db_path provided
        if self._store is None and db_path is None:
            self._store = InMemoryMessageStore()

        if db_path is not None:
            sstore = SessionStore(db_path)
            self._manager = SessionManager(sstore)
            self._session = self._manager.get_or_create(session_key)

    @property
    def manager(self) -> SessionManager | None:
        return self._manager

    @property
    def session(self) -> Session | None:
        return self._session

    @property
    def store(self) -> MessageStore | None:
        return self._store

    def set_session_key(self, key: str) -> None:
        self.session_key = key
        if self._manager:
            self._session = self._manager.get_or_create(key)

    def get_history(self, session_id: str = "") -> list[dict]:
        """Get history. Uses session cursor when available; falls back to store."""
        # Use session-based history if available
        sess = self._session
        if sess is not None:
            sid = session_id or self.session_key
            if sid != self.session_key and self._manager is not None:
                sess = self._manager.get_or_create(sid)
            start_idx = sess.last_consolidated if sess.last_consolidated > 0 else None
            return get_history(sess, max_messages=500, start_index=start_idx)

        # Legacy store-based history
        sid = session_id or self.session_key
        if self._store is not None:
            return self._store.list_messages(session_id=sid)
        return []

    def get_full_history(self, session_id: str = "") -> list[dict]:
        """Get full history without consolidation cursor filtering."""
        sess = self._session
        if sess is not None:
            sid = session_id or self.session_key
            if sid != self.session_key and self._manager is not None:
                sess = self._manager.get_or_create(sid)
            return get_history(sess, max_messages=500, start_index=None)

        sid = session_id or self.session_key
        if self._store is not None:
            return self._store.list_messages(session_id=sid)
        return []

    def append_user_message(self, session_id: str, content: str) -> None:
        # Session-based
        if self._session is not None and self._manager is not None:
            sid = session_id or self.session_key
            if sid != self.session_key:
                sess = self._manager.get_or_create(sid)
            else:
                sess = self._session
            sess.messages.append({"role": "user", "content": content})
            return

        # Legacy store-based
        if self._store is not None:
            self._store.append_message(
                session_id=session_id, role="user", content=content
            )

    def append_assistant_message(self, session_id: str, content: str) -> None:
        # Session-based
        if self._session is not None and self._manager is not None:
            sid = session_id or self.session_key
            if sid != self.session_key:
                sess = self._manager.get_or_create(sid)
            else:
                sess = self._session
            sess.messages.append({"role": "assistant", "content": content})
            return

        # Legacy store-based
        if self._store is not None:
            self._store.append_message(
                session_id=session_id, role="assistant", content=content
            )

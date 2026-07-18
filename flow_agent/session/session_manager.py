"""SessionManager: in-memory cache + async persistence for sessions (spec 1-2).

Implements:
- 1a: get_or_create(key) with cache lookup
- 1b: _load(key) from SQLite reconstruction
- 1c: Session object construction
- 1d: Cache and return
- 2a: Per-session async lock
- 2b: Only persist un-persisted messages
- 2c: insert_message() with stable id delegation
- 2d: upsert_session() after persist
- 2e: Refresh cache
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flow_agent.session.session_models import Session
from flow_agent.session.session_store import SessionStore

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages session lifecycle: cache, load, persist, history.

    Usage:
        mgr = SessionManager(SessionStore(db_path))
        session = mgr.get_or_create("default")
        await mgr.append_messages(session, [{"role": "user", "content": "hi"}])
        history = mgr.get_history(session, max_messages=50)
    """

    def __init__(self, store: SessionStore) -> None:
        self._store = store
        self._cache: dict[str, Session] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # ── Session Loading (spec 1) ──

    def get_or_create(self, key: str) -> Session:
        """Get cached session or load from SQLite (spec 1a).

        Returns existing session if cached; otherwise loads from SQLite (spec 1b),
        constructs a Session object (spec 1c), caches it (spec 1d), and returns.
        """
        if key in self._cache:
            return self._cache[key]

        session = self._load(key)
        if session is None:
            session = Session(key=key)
            now = datetime.now(timezone.utc)
            self._store.upsert_session(
                key=key,
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
                last_consolidated=0,
                metadata={},
            )

        self._cache[key] = session
        return session

    def _load(self, key: str) -> Session | None:
        """Reconstruct Session from SQLite (spec 1b)."""
        meta = self._store.get_session_meta(key)
        if meta is None:
            return None
        messages = self._store.fetch_session_messages(key)
        return Session(
            key=key,
            messages=messages,
            created_at=meta.created_at,
            updated_at=meta.updated_at,
            last_consolidated=meta.last_consolidated,
            metadata=meta.metadata,
        )

    def list_sessions(self) -> list[str]:
        """List all cached session keys."""
        return list(self._cache.keys())

    def append_message(
        self,
        session_key: str,
        role: str,
        content: str,
        *,
        tool_chain: list | None = None,
        extra: dict | None = None,
    ) -> dict[str, Any]:
        """同步写入一条会话消息，供被动回合结束时可靠持久化。"""
        session = self.get_or_create(session_key)
        seq = self._store.get_next_seq(session_key)
        timestamp = datetime.now(timezone.utc).isoformat()
        message = {
            "role": role,
            "content": content,
            "tool_chain": tool_chain or [],
            "extra": extra or {},
            "timestamp": timestamp,
            "seq": seq,
            "session_key": session_key,
        }
        message["id"] = self._store.insert_message(
            session_key=session_key,
            seq=seq,
            role=role,
            content=content,
            tool_chain=message["tool_chain"],
            extra=message["extra"],
            ts=timestamp,
        )
        session.messages.append(message)
        session.updated_at = datetime.now(timezone.utc)
        self._store.upsert_session(
            key=session.key,
            created_at=session.created_at.isoformat(),
            updated_at=session.updated_at.isoformat(),
            last_consolidated=session.last_consolidated,
            metadata=session.metadata,
        )
        return message

    # ── Message Persistence (spec 2) ──

    def _lock(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def append_messages(self, session: Session, messages: list[dict]) -> None:
        """Persist new messages with stable ids and update session metadata (spec 2a-2e)."""
        session.updated_at = datetime.now(timezone.utc)
        msgs_copy = list(messages)

        async with self._lock(session.key):
            for msg in msgs_copy:
                if msg.get("id"):
                    continue  # spec 2b: skip already-persisted messages
                seq = self._store.get_next_seq(session.key)
                ts = str(msg.get("timestamp") or datetime.now(timezone.utc).isoformat())
                tool_chain = msg.get("tool_chain", [])
                extra = msg.get("extra") or msg.get("metadata", {})

                row_id = self._store.insert_message(
                    session_key=session.key,
                    seq=seq,
                    role=msg.get("role", "user"),
                    content=msg.get("content", ""),
                    tool_chain=tool_chain if isinstance(tool_chain, list) else [],
                    extra=extra if isinstance(extra, dict) else {},
                    ts=ts,
                )
                # Backfill stable id into the message dict
                msg["id"] = row_id
                msg["seq"] = seq
                msg["session_key"] = session.key

                # Also add to in-memory session
                session.messages.append(msg)

            # spec 2d: Update session metadata
            self._store.upsert_session(
                key=session.key,
                created_at=session.created_at.isoformat(),
                updated_at=session.updated_at.isoformat(),
                last_consolidated=session.last_consolidated,
                metadata=session.metadata,
            )

            # spec 2e: Refresh cache
            self._cache[session.key] = session

    async def update_consolidated(self, session: Session, new_cursor: int) -> None:
        """Update last_consolidated cursor and persist (spec 4c)."""
        session.last_consolidated = new_cursor
        self._store.update_last_consolidated(session.key, new_cursor)
        self._cache[session.key] = session

    def mark_consolidated(self, session: Session, new_cursor: int) -> None:
        """同步更新归档游标，供回合后归档流程使用。"""
        session.last_consolidated = new_cursor
        session.updated_at = datetime.now(timezone.utc)
        self._store.update_last_consolidated(session.key, new_cursor)
        self._cache[session.key] = session

    # ── Undo (spec 5) ──

    def find_last_passive_turn(self, session: Session) -> tuple[list[str], int, int] | None:
        """Find the last passive turn (user + assistant message pair) for undo (spec 5a).

        Returns:
            Tuple of (message_ids_to_delete, start_index, end_index) or None.
        """
        return find_last_passive_turn(session.messages)

    async def undo_last_turn(self, session: Session) -> int:
        """Delete the last passive turn and rollback cursor (spec 5b).

        Returns:
            Number of messages deleted.
        """
        result = self.find_last_passive_turn(session)
        if result is None:
            return 0

        ids_to_delete, start_idx, end_idx = result

        # Calculate the new last_consolidated (rollback if needed)
        new_cursor = session.last_consolidated
        if start_idx < session.last_consolidated:
            new_cursor = start_idx

        deleted = self._store.delete_session_messages_and_update_cursor(
            session_key=session.key,
            ids=ids_to_delete,
            last_consolidated=new_cursor,
        )

        # Remove from in-memory session
        kept = []
        for msg in session.messages:
            if msg.get("id") not in ids_to_delete:
                kept.append(msg)
        session.messages = kept
        session.last_consolidated = new_cursor
        self._cache[session.key] = session

        return deleted


# ── Undo helper (spec 5a) ──

def find_last_passive_turn(messages: list[dict[str, Any]]) -> tuple[list[str], int, int] | None:
    """Find the last passive turn (user + assistant message pair) for undo.

    Walks backwards from the end, skipping context-frame messages, to find
    the last assistant message and its preceding user message.

    Returns:
        (message_ids_to_delete, start_index, end_index) or None if not found.
    """
    assistant_idx = None

    # Walk backwards to find the last assistant message
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        role = msg.get("role", "")
        is_proactive = msg.get("proactive", False)
        is_frame = msg.get("context_frame", False)

        # Skip context frame messages
        if is_frame:
            continue

        if role == "assistant" and not is_proactive:
            assistant_idx = i
            break

    if assistant_idx is None:
        return None

    # Walk backwards from assistant to find the preceding user message
    user_idx = None
    for i in range(assistant_idx - 1, -1, -1):
        role = messages[i].get("role", "")
        is_frame = messages[i].get("context_frame", False)
        if is_frame:
            continue
        if role == "user":
            user_idx = i
            break

    if user_idx is None:
        return None

    # Collect all message ids in this turn (user through assistant, including tool chain messages)
    ids_to_delete: list[str] = []
    for i in range(user_idx, assistant_idx + 1):
        mid = messages[i].get("id")
        if mid:
            ids_to_delete.append(mid)

    return ids_to_delete, user_idx, assistant_idx

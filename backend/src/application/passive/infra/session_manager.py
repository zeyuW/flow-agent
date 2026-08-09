"""被动会话运行时：上下文门面、缓存管理和持久化协调。

包含以下职责：
- 1a：通过缓存查找或创建会话；
- 1b：从 SQLite 重建会话；
- 1c：构造 Session 对象；
- 1d：写入缓存并返回；
- 2a：提供会话级异步锁；
- 2b：只持久化尚未保存的消息；
- 2c：委托存储层写入稳定消息 ID；
- 2d：持久化后更新会话；
- 2e：刷新缓存。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from application.passive.domain.session import Session
from application.passive.infra.history import get_history
from application.passive.infra.session_store import SessionStore

logger = logging.getLogger(__name__)


class ConversationContext:
    """Agent 使用的会话上下文门面。"""

    def __init__(
        self,
        db_path: Path | None = None,
        session_key: str = "default",
        session_manager: SessionManager | None = None,
    ) -> None:
        self.session_key = session_key
        self._temporary_dir: TemporaryDirectory[str] | None = None
        if session_manager is not None:
            self._manager = session_manager
        else:
            if db_path is None:
                self._temporary_dir = TemporaryDirectory(prefix="flow-agent-session-")
                db_path = Path(self._temporary_dir.name) / "sessions.db"
            self._manager = SessionManager(SessionStore(db_path))
        self._session = self._manager.get_or_create(session_key)

    @property
    def manager(self) -> SessionManager:
        return self._manager

    @property
    def session(self) -> Session:
        return self._session

    def set_session_key(self, key: str) -> None:
        self.session_key = key
        self._session = self._manager.get_or_create(key)

    def get_history(self, session_id: str = "") -> list[dict]:
        """读取当前会话的可用历史消息。"""
        sid = session_id or self.session_key
        session = self._session if sid == self.session_key else self._manager.get_or_create(sid)
        start_idx = session.last_consolidated if session.last_consolidated > 0 else None
        return get_history(session, max_messages=500, start_index=start_idx)

    def get_full_history(self, session_id: str = "") -> list[dict]:
        """读取当前会话的完整历史消息。"""
        sid = session_id or self.session_key
        session = self._session if sid == self.session_key else self._manager.get_or_create(sid)
        return get_history(session, max_messages=500, start_index=None)

    def append_turn(
        self,
        session_id: str,
        user_content: str,
        assistant_content: str,
        *,
        assistant_tool_chain: list | None = None,
    ) -> None:
        """原子保存完整回合，保证恢复时不会出现半个回合。"""
        self._manager.append_turn(
            session_id or self.session_key,
            user_content,
            assistant_content,
            assistant_tool_chain=assistant_tool_chain,
        )

    def append_user_message(self, session_id: str, content: str) -> None:
        self._manager.append_message(session_id or self.session_key, "user", content)

    def append_assistant_message(self, session_id: str, content: str) -> None:
        self._manager.append_message(
            session_id or self.session_key,
            "assistant",
            content,
        )


class SessionManager:
    """管理会话生命周期，包括缓存、加载、持久化和历史访问。"""

    def __init__(self, store: SessionStore) -> None:
        self._store = store
        self._cache: dict[str, Session] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # ── 会话加载（规范 1） ──

    def get_or_create(self, key: str) -> Session:
        """获取缓存中的会话，或从 SQLite 加载会话（规范 1a）。

        如果缓存中存在则直接返回；否则从 SQLite 加载（规范 1b），
        构造 Session 对象（规范 1c），写入缓存（规范 1d）后返回。
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
        """从 SQLite 重建 Session 对象（规范 1b）。"""
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
        """列出所有已缓存的会话键。"""
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


    def append_turn(
        self,
        session_key: str,
        user_content: str,
        assistant_content: str,
        *,
        user_extra: dict[str, Any] | None = None,
        assistant_extra: dict[str, Any] | None = None,
        assistant_tool_chain: list | None = None,
    ) -> list[dict[str, Any]]:
        """原子持久化完整回合，并同步更新内存缓存。"""

        session = self.get_or_create(session_key)
        messages = self._store.insert_turn(
            session_key,
            user_content,
            assistant_content,
            user_extra=user_extra,
            assistant_extra=assistant_extra,
            assistant_tool_chain=assistant_tool_chain,
        )
        session.messages.extend(messages)
        session.updated_at = datetime.now(timezone.utc)
        self._cache[session_key] = session
        return messages

    # ── 消息持久化（规范 2） ──

    def _lock(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def append_messages(self, session: Session, messages: list[dict]) -> None:
        """持久化新消息、写入稳定 ID，并更新会话元数据（规范 2a-2e）。"""
        session.updated_at = datetime.now(timezone.utc)
        msgs_copy = list(messages)

        async with self._lock(session.key):
            for msg in msgs_copy:
                if msg.get("id"):
                    continue  # 规范 2b：跳过已经持久化的消息
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
                # 将稳定 ID 回填到消息字典
                msg["id"] = row_id
                msg["seq"] = seq
                msg["session_key"] = session.key

                # 同时追加到内存会话
                session.messages.append(msg)

            # 规范 2d：更新会话元数据
            self._store.upsert_session(
                key=session.key,
                created_at=session.created_at.isoformat(),
                updated_at=session.updated_at.isoformat(),
                last_consolidated=session.last_consolidated,
                metadata=session.metadata,
            )

            # 规范 2e：刷新缓存
            self._cache[session.key] = session

    async def update_consolidated(self, session: Session, new_cursor: int) -> None:
        """更新 last_consolidated 归档游标并持久化（规范 4c）。"""
        session.last_consolidated = new_cursor
        self._store.update_last_consolidated(session.key, new_cursor)
        self._cache[session.key] = session

    def mark_consolidated(self, session: Session, new_cursor: int) -> None:
        """同步更新归档游标，供回合后归档流程使用。"""
        session.last_consolidated = new_cursor
        session.updated_at = datetime.now(timezone.utc)
        self._store.update_last_consolidated(session.key, new_cursor)
        self._cache[session.key] = session

    # ── 撤销（规范 5） ──

    def find_last_passive_turn(self, session: Session) -> tuple[list[str], int, int] | None:
        """查找最后一轮被动对话，用于撤销（规范 5a）。

        返回：
            （待删除消息 ID、起始位置、结束位置）或 None。
        """
        return find_last_passive_turn(session.messages)

    async def undo_last_turn(self, session: Session) -> int:
        """删除最后一轮被动对话并回滚归档游标（规范 5b）。

        返回：
            删除的消息数量。
        """
        result = self.find_last_passive_turn(session)
        if result is None:
            return 0

        ids_to_delete, start_idx, end_idx = result

        # 计算新的 last_consolidated，必要时回滚归档游标
        new_cursor = session.last_consolidated
        if start_idx < session.last_consolidated:
            new_cursor = start_idx

        deleted = self._store.delete_session_messages_and_update_cursor(
            session_key=session.key,
            ids=ids_to_delete,
            last_consolidated=new_cursor,
        )

        # 从内存会话中移除消息
        kept = []
        for msg in session.messages:
            if msg.get("id") not in ids_to_delete:
                kept.append(msg)
        session.messages = kept
        session.last_consolidated = new_cursor
        self._cache[session.key] = session

        return deleted


# ── 撤销辅助函数（规范 5a） ──

def find_last_passive_turn(messages: list[dict[str, Any]]) -> tuple[list[str], int, int] | None:
    """查找最后一轮被动对话，用于撤销。

    从末尾反向遍历，跳过上下文标记消息，查找最后一条助手消息及其前面的用户消息。

    返回：
        （待删除消息 ID、起始位置、结束位置），找不到时返回 None。
    """
    assistant_idx = None

    # 反向查找最后一条助手消息
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        role = msg.get("role", "")
        is_proactive = msg.get("proactive", False)
        is_frame = msg.get("context_frame", False)

        # 跳过上下文标记消息
        if is_frame:
            continue

        if role == "assistant" and not is_proactive:
            assistant_idx = i
            break

    if assistant_idx is None:
        return None

    # 从助手消息开始反向查找前面的用户消息
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

    # 收集本轮从用户到助手的全部消息 ID，包括工具调用链消息
    ids_to_delete: list[str] = []
    for i in range(user_idx, assistant_idx + 1):
        mid = messages[i].get("id")
        if mid:
            ids_to_delete.append(mid)

    return ids_to_delete, user_idx, assistant_idx

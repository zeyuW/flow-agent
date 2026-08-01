"""基于 SessionManager 的会话上下文。"""

from pathlib import Path
from tempfile import TemporaryDirectory

from modules.conversation.infra.session_manager import SessionManager
from modules.conversation.infra.session_store import SessionStore
from modules.conversation.domain.session import Session
from modules.conversation.infra.history import get_history


class ConversationContext:
    """使用统一会话存储管理历史消息。"""

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

        sid = session_id or self.session_key
        self._manager.append_turn(
            sid,
            user_content,
            assistant_content,
            assistant_tool_chain=assistant_tool_chain,
        )

    def append_user_message(self, session_id: str, content: str) -> None:
        sid = session_id or self.session_key
        self._manager.append_message(sid, "user", content)

    def append_assistant_message(self, session_id: str, content: str) -> None:
        sid = session_id or self.session_key
        self._manager.append_message(sid, "assistant", content)

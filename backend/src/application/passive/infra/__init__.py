"""被动对话的会话存储和历史重建适配器。"""

from application.passive.infra.history import get_history
from application.passive.infra.session_manager import ConversationContext, SessionManager
from application.passive.infra.session_store import SessionStore

__all__ = ["ConversationContext", "SessionManager", "SessionStore", "get_history"]

from flow_agent.memory.store import InMemoryMessageStore, MessageStore


class ConversationContext:
    def __init__(self, store: MessageStore | None = None) -> None:
        self.store = store or InMemoryMessageStore()

    def get_history(self, session_id: str) -> list[dict[str, str]]:
        return self.store.list_messages(session_id=session_id)

    def append_user_message(self, session_id: str, content: str) -> None:
        self.store.append_message(session_id=session_id, role="user", content=content)

    def append_assistant_message(self, session_id: str, content: str) -> None:
        self.store.append_message(session_id=session_id, role="assistant", content=content)

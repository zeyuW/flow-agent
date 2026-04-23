from dataclasses import dataclass

from flow_agent.memory.store import MessageStore


@dataclass(slots=True)
class MemoryFacade:
    """Unified entrypoint for memory operations."""

    store: MessageStore

    def append_user_message(self, session_id: str, content: str) -> None:
        self.store.append_message(session_id, "user", content)

    def append_assistant_message(self, session_id: str, content: str) -> None:
        self.store.append_message(session_id, "assistant", content)

    def list_history(self, session_id: str) -> list[dict[str, str]]:
        return self.store.list_messages(session_id)


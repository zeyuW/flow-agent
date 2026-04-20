class ConversationContext:
    def __init__(self) -> None:
        self.history: list[dict[str, str]] = []

    def get_history(self) -> list[dict[str, str]]:
        return list(self.history)

    def append_user_message(self, content: str) -> None:
        self.history.append({"role": "user", "content": content})

    def append_assistant_message(self, content: str) -> None:
        self.history.append({"role": "assistant", "content": content})

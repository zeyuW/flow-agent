"""对话应用依赖的稳定端口。"""

from typing import Protocol


class ConversationHistory(Protocol):
    """Agent 读写会话历史所需的最小能力。"""

    def get_history(self, conversation_id: str = "") -> list[dict]:
        """读取可用于下一轮推理的历史消息。"""

        ...

    def append_turn(
        self,
        conversation_id: str,
        user_content: str,
        assistant_content: str,
        *,
        assistant_tool_chain: list | None = None,
    ) -> None:
        """原子写入一轮用户和助手消息。"""

        ...

    def append_user_message(self, conversation_id: str, content: str) -> None:
        """写入单条用户消息。"""

        ...

    def append_assistant_message(self, conversation_id: str, content: str) -> None:
        """写入单条助手消息。"""

        ...

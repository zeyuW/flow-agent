"""记忆业务对其他应用模块暴露的稳定端口。

其他业务只依赖这里定义的协议，不直接依赖 Markdown、SQLite 或向量库实现。
具体实现由 ``memory.app`` 和 ``memory.infra`` 提供，并在 bootstrap 中装配。
"""

from __future__ import annotations

from typing import Protocol


class MemoryPromptStore(Protocol):
    """提供稳定档案和近期上下文的提示词内容。"""

    def render_prompt_memory(self) -> str:
        """返回可直接注入 Agent 提示词的记忆文本。"""


class MemoryQueryService(Protocol):
    """提供面向 Agent 提示词的长期记忆检索能力。"""

    def retrieve_for_prompt(
        self,
        text: str,
        max_items: int = 8,
        max_chars: int = 2000,
    ) -> str:
        """根据输入文本检索并格式化长期记忆。"""


__all__ = ["MemoryPromptStore", "MemoryQueryService"]

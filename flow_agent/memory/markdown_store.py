"""Markdown 记忆层：人类可读的长期档案存储。

实现 spec 1b：初始化和管理 MEMORY.md（用户档案）、HISTORY.md（事件日志）、
RECENT_CONTEXT.md（近期上下文压缩）等文件。

这些文件存储在 .flow/memory/ 目录下，可以通过文本编辑器直接查看和编辑。
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Markdown 文件模版
MEMORY_TEMPLATE = """# 用户记忆档案

> 本文件由 FlowAgent 自动维护，记录跨对话的用户信息与偏好。
> 最后更新：{updated_at}

---

## 身份信息 (Identity)
<!-- 用户的基本身份信息 -->


## 偏好设置 (Preferences)
<!-- 用户的使用偏好 -->


## 目标与计划 (Goals)
<!-- 用户的目标和计划 -->


## 约束限制 (Constraints)
<!-- 用户的行为约束和限制 -->


"""

HISTORY_TEMPLATE = """# 事件历史

> 本文件记录重要的对话事件和里程碑。
> 最后更新：{updated_at}

---

## 事件列表

<!-- 格式：- [YYYY-MM-DD] 事件描述 -->


"""

RECENT_CONTEXT_TEMPLATE = """# 近期上下文

> 最近对话的压缩摘要，用于上下文窗口恢复。
> 最后更新：{updated_at}

---

## 近期摘要

*暂无近期对话摘要。*

"""


@dataclass(slots=True)
class MarkdownStore:
    """Markdown 记忆文件管理层。

    管理三个核心文件：
    - MEMORY.md: 用户长期档案（身份、偏好、目标、约束）
    - HISTORY.md: 重要事件的时间线记录
    - RECENT_CONTEXT.md: 最近对话的压缩摘要
    """

    root: Path

    @property
    def memory_file(self) -> Path:
        return self.root / "MEMORY.md"

    @property
    def history_file(self) -> Path:
        return self.root / "HISTORY.md"

    @property
    def recent_context_file(self) -> Path:
        return self.root / "RECENT_CONTEXT.md"

    def initialize(self) -> None:
        """初始化所有 Markdown 文件（spec 1b）。"""
        self.root.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        for path, template in [
            (self.memory_file, MEMORY_TEMPLATE),
            (self.history_file, HISTORY_TEMPLATE),
            (self.recent_context_file, RECENT_CONTEXT_TEMPLATE),
        ]:
            if not path.exists():
                path.write_text(
                    template.format(updated_at=now),
                    encoding="utf-8",
                )
                logger.info("created markdown file: %s", path)

    def read_memory(self) -> str:
        """读取 MEMORY.md 完整内容。"""
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def read_history(self) -> str:
        """读取 HISTORY.md 完整内容。"""
        if self.history_file.exists():
            return self.history_file.read_text(encoding="utf-8")
        return ""

    def read_recent_context(self) -> str:
        """读取 RECENT_CONTEXT.md 完整内容。"""
        if self.recent_context_file.exists():
            return self.recent_context_file.read_text(encoding="utf-8")
        return ""

    def append_event(self, event: str, timestamp: str | None = None) -> None:
        """向 HISTORY.md 追加一条事件记录。

        Args:
            event: 事件描述。
            timestamp: 可选的 ISO 时间戳。
        """
        if not self.history_file.exists():
            self.initialize()

        ts = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        entry = f"- [{ts}] {event}\n"

        with self.history_file.open("a", encoding="utf-8") as f:
            f.write(entry)

        # 更新最后修改时间
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        content = self.history_file.read_text(encoding="utf-8")
        content = _update_timestamp(content, now)
        self.history_file.write_text(content, encoding="utf-8")

    def update_recent_context(self, summary: str) -> None:
        """更新 RECENT_CONTEXT.md 的近期摘要。

        Args:
            summary: 最近的对话摘要文本。
        """
        if not self.recent_context_file.exists():
            self.initialize()

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        template = """# 近期上下文

> 最近对话的压缩摘要，用于上下文窗口恢复。
> 最后更新：{updated_at}

---

## 近期摘要

{summary}
"""
        content = template.format(updated_at=now, summary=summary)
        self.recent_context_file.write_text(content, encoding="utf-8")

    def update_memory_section(self, section: str, content: str) -> None:
        """更新 MEMORY.md 的指定 section。

        Args:
            section: 要更新的 section 标题（如 "身份信息"）。
            content: 附加到 section 下的内容。
        """
        if not self.memory_file.exists():
            self.initialize()

        text = self.memory_file.read_text(encoding="utf-8")
        marker = f"## {section}"
        if marker in text:
            # 在 section 标题下追加内容
            idx = text.index(marker) + len(marker)
            next_section = text.find("\n## ", idx)
            if next_section == -1:
                next_section = len(text)
            # 找到 section 内容结束位置
            section_end = text.find("\n\n", idx)
            if section_end != -1 and section_end < next_section:
                insert_pos = section_end + 2
            else:
                insert_pos = idx + 1
            new_text = text[:insert_pos] + content + "\n" + text[insert_pos:]
        else:
            new_text = text.rstrip() + f"\n\n## {section}\n{content}\n"

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        new_text = _update_timestamp(new_text, now)
        self.memory_file.write_text(new_text, encoding="utf-8")


def _update_timestamp(text: str, timestamp: str) -> str:
    """更新 Markdown 文件头部的时间戳。"""
    import re

    return re.sub(
        r"> 最后更新：.*",
        f"> 最后更新：{timestamp}",
        text,
        count=1,
    )

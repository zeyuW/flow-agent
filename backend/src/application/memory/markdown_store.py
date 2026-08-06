"""Markdown 记忆层：人类可读的长期档案存储。

负责初始化和管理 MEMORY.md（用户档案）、HISTORY.md（事件日志）、
RECENT_CONTEXT.md（近期上下文压缩）等文件。

这些文件存储在 .flow/memory/ 目录下，可以通过文本编辑器直接查看和编辑。
"""

import logging
import os
import re
import threading
from dataclasses import dataclass, field
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


## 事实信息 (Facts)
<!-- 用户明确说明的稳定事实 -->


## 偏好设置 (Preferences)
<!-- 用户的使用偏好 -->


## 需求记录 (Needs)
<!-- 用户提出的需求、目标和计划 -->


## 目标与计划 (Goals)
<!-- 用户的目标和计划 -->


## 约束限制 (Constraints)
<!-- 用户的行为约束和限制 -->


"""

SELF_TEMPLATE = """# 助手自我认知

> 本文件用于保存助手与当前用户之间稳定、必要的协作认识。
> 最后更新：{updated_at}

---

## 助手定位
- 在尊重用户边界的前提下，提供可靠、简洁的协作支持。

## 对用户的理解
*暂无稳定认识。*

## 协作关系
*暂无需要长期保存的协作约定。*
"""

_MEMORY_SECTION_SPECS = (
    ("身份信息", "用户的基本身份信息"),
    ("事实信息", "用户明确说明的稳定事实"),
    ("偏好设置", "用户的使用偏好"),
    ("需求记录", "用户提出的需求、目标和计划"),
    ("目标与计划", "用户的目标和计划"),
    ("约束限制", "用户的行为约束和限制"),
)

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

## 压缩摘要

*尚未生成近期摘要。*

## 持续话题

*暂无持续话题。*

## 最近对话

*暂无最近对话。*

"""

PENDING_TEMPLATE = '''# 待归档用户画像

> 本文件是高频写入缓冲；定时归档完成后会清空其中的稳定事实。
> 最后更新：{updated_at}

---

## 待归档事实

*暂无待归档事实。*

'''


@dataclass(slots=True)
class MarkdownStore:
    """Markdown 记忆文件管理层。

    管理五个核心文件：
    - MEMORY.md: 用户长期档案（身份、偏好、目标、约束）
    - SELF.md: 助手与当前用户的稳定协作认知
    - HISTORY.md: 重要事件的时间线记录
    - RECENT_CONTEXT.md: 最近对话的压缩摘要
    - PENDING.md: 等待定时归档的稳定用户事实
    """

    root: Path
    _lock: threading.RLock = field(
        default_factory=threading.RLock,
        init=False,
        repr=False,
    )

    @property
    def memory_file(self) -> Path:
        return self.root / "MEMORY.md"

    @property
    def history_file(self) -> Path:
        return self.root / "HISTORY.md"

    @property
    def self_file(self) -> Path:
        return self.root / "SELF.md"

    @property
    def recent_context_file(self) -> Path:
        return self.root / "RECENT_CONTEXT.md"

    @property
    def pending_file(self) -> Path:
        return self.root / "PENDING.md"

    @property
    def pending_snapshot_file(self) -> Path:
        """返回归档器处理中的待处理快照路径。"""
        return self.root / "PENDING.snapshot.md"

    @property
    def journal_dir(self) -> Path:
        return self.root / "journal"

    @property
    def consolidation_db(self) -> Path:
        return self.root / "consolidation_writes.db"

    def initialize(self) -> None:
        """初始化所有 Markdown 文件（spec 1b）。"""
        self.root.mkdir(parents=True, exist_ok=True)
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        for path, template in [
            (self.memory_file, MEMORY_TEMPLATE),
            (self.self_file, SELF_TEMPLATE),
            (self.history_file, HISTORY_TEMPLATE),
            (self.recent_context_file, RECENT_CONTEXT_TEMPLATE),
            (self.pending_file, PENDING_TEMPLATE),
        ]:
            if not path.exists():
                path.write_text(
                    template.format(updated_at=now),
                    encoding="utf-8",
                )
                logger.info("created markdown file: %s", path)

        self._migrate_memory_sections()
        self._recover_pending_snapshot()

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

    def read_self(self) -> str:
        """读取 SELF.md 完整内容。"""
        if self.self_file.exists():
            return self.self_file.read_text(encoding="utf-8")
        return ""

    def read_recent_context(self) -> str:
        """读取 RECENT_CONTEXT.md 完整内容。"""
        if self.recent_context_file.exists():
            return self.recent_context_file.read_text(encoding="utf-8")
        return ""

    def read_pending(self) -> str:
        """读取 PENDING.md 完整内容。"""
        if self.pending_file.exists():
            return self.pending_file.read_text(encoding="utf-8")
        return ""

    def append_memory_item(
        self,
        memory_type: str,
        summary: str,
        source_label: str = "",
    ) -> None:
        """把结构化记忆追加到合适的 Markdown 文件。"""
        line = f"- {summary.strip()}"
        if len(line) <= 2:
            return

        if memory_type == "task":
            self.append_pending(summary)
            return

        section_by_type = {
            "fact": "事实信息",
            "preference": "偏好设置",
            "need": "需求记录",
            "procedure": "约束限制",
            "event": "目标与计划",
        }
        section = section_by_type.get(memory_type, "事实信息")
        if memory_type == "fact" and source_label == "identity":
            section = "身份信息"
        self._append_unique_line(self.memory_file, section, line)

    def append_pending(self, summary: str) -> None:
        """向待归档缓冲追加一项用户明确希望保留的信息。"""
        line = f"- [requested_memory] {summary.strip()}"
        if len(line) <= 2:
            return
        with self._lock:
            self._append_unique_line(self.pending_file, "待归档事实", line)

    def append_history_entry(
        self,
        summary: str,
        source_ref: str,
        timestamp: str | None = None,
    ) -> bool:
        """按来源幂等追加一条用户事件，并同步写入日记文件。"""
        text = summary.strip()
        if not text or not source_ref.strip():
            return False
        ts = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        line = f"- [{ts}] {text}"
        inserted = self._append_source_entry(
            self.history_file,
            "事件列表",
            line,
            source_ref,
        )
        if inserted:
            day = ts[:10]
            journal = self.journal_dir / f"{day}.md"
            if not journal.exists():
                journal.write_text(
                    f"# {day} 记忆日记\n\n",
                    encoding="utf-8",
                )
            self._append_source_entry(journal, "", line, source_ref)
        return inserted

    def append_pending_item(
        self,
        tag: str,
        content: str,
        source_ref: str,
    ) -> bool:
        """按来源幂等追加待归档事实。"""
        normalized_tag = tag.strip().lower()
        text = content.strip()
        if not normalized_tag or not text or not source_ref.strip():
            return False
        with self._lock:
            return self._append_source_entry(
                self.pending_file,
                "待归档事实",
                f"- [{normalized_tag}] {text}",
                source_ref,
            )

    def clear_pending(self) -> None:
        """在画像归档成功后清空待处理事实缓冲。"""
        with self._lock:
            self._write_empty_pending()

    def snapshot_pending(self) -> Path | None:
        """原子切出待归档快照，让新事实继续写入新的缓冲文件。"""
        with self._lock:
            if not self.pending_file.exists():
                self.initialize()
            if self.pending_snapshot_file.exists():
                logger.warning("检测到尚未处理完成的待归档快照：%s", self.pending_snapshot_file)
                return None
            if not _has_pending_entries(self.pending_file.read_text(encoding="utf-8")):
                return None
            os.replace(self.pending_file, self.pending_snapshot_file)
            self._write_empty_pending()
            return self.pending_snapshot_file

    def commit_pending_snapshot(self, snapshot: Path) -> None:
        """确认快照内容已写入长期档案后删除该快照。"""
        with self._lock:
            if snapshot == self.pending_snapshot_file and snapshot.exists():
                snapshot.unlink()

    def rollback_pending_snapshot(self, snapshot: Path) -> None:
        """归档失败时把快照合并回缓冲，确保用户事实不会丢失。"""
        with self._lock:
            if snapshot != self.pending_snapshot_file or not snapshot.exists():
                return
            snapshot_text = snapshot.read_text(encoding="utf-8")
            current_text = self.pending_file.read_text(encoding="utf-8") if self.pending_file.exists() else ""
            restored = _merge_pending_text(current_text, snapshot_text)
            self.pending_file.write_text(restored, encoding="utf-8")
            snapshot.unlink()

    def update_recent_compression(self, summary: str, ongoing_threads: str = "") -> None:
        """更新归档后的近期压缩摘要，同时保留每回合刷新出的最近对话。"""
        if not self.recent_context_file.exists():
            self.initialize()
        current = self.recent_context_file.read_text(encoding="utf-8")
        recent_turns = _section_content(current, "最近对话") or "*暂无最近对话。*"
        compression = summary.strip() or "*尚未生成近期摘要。*"
        threads = ongoing_threads.strip() or "*暂无持续话题。*"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self.recent_context_file.write_text(
            _render_recent_context(compression, threads, recent_turns, now),
            encoding="utf-8",
        )

    def render_prompt_memory(self) -> str:
        """渲染应注入提示词的稳定档案与近期压缩，不包含待归档缓冲。"""
        blocks: list[str] = []
        self_text = self.read_self().strip()
        if self_text:
            blocks.append(f"## 助手自我认知\n\n{self_text}")
        memory_text = self.read_memory().strip()
        if memory_text:
            blocks.append(f"## 长期用户画像\n\n{memory_text}")
        recent_text = self.read_recent_context()
        compression = _section_content(recent_text, "压缩摘要")
        threads = _section_content(recent_text, "持续话题")
        recent_parts = [part for part in (compression, threads) if part]
        if recent_parts:
            blocks.append("## 近期上下文\n\n" + "\n\n".join(recent_parts))
        return "\n\n".join(blocks)

    def write_memory(self, content: str) -> None:
        """原子覆盖长期用户画像。"""
        text = content.strip()
        if not text:
            raise ValueError("长期用户画像不能为空")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self.memory_file.write_text(
            _update_timestamp(text + "\n", now),
            encoding="utf-8",
        )

    def write_self(self, content: str) -> None:
        """原子覆盖助手自我认知。"""
        text = content.strip()
        if not text:
            raise ValueError("助手自我认知不能为空")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self.self_file.write_text(
            _update_timestamp(text + "\n", now),
            encoding="utf-8",
        )

    def refresh_recent_turns(
        self,
        messages: list[dict],
        limit: int = 8,
    ) -> None:
        """每轮更新轻量近期对话，不改动压缩摘要。"""
        if not self.recent_context_file.exists():
            self.initialize()
        recent_messages = messages[-max(2, limit):]
        lines: list[str] = []
        for message in recent_messages:
            role = str(message.get("role", ""))
            if role not in {"user", "assistant"}:
                continue
            content = str(message.get("content", "")).replace("\n", " ").strip()
            if not content:
                continue
            label = "用户" if role == "user" else "助手"
            lines.append(f"- [{label}] {content[:240]}")
        recent_block = "\n".join(lines) or "*暂无最近对话。*"
        current = self.recent_context_file.read_text(encoding="utf-8")
        compression = _section_content(current, "压缩摘要")
        if not compression:
            compression = "*尚未生成近期摘要。*"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        ongoing_threads = _section_content(current, "持续话题") or "*暂无持续话题。*"
        self.recent_context_file.write_text(
            _render_recent_context(compression, ongoing_threads, recent_block, now),
            encoding="utf-8",
        )

    def _append_unique_line(self, path: Path, section: str, line: str) -> None:
        """向指定 section 追加一行，已存在时只更新时间戳。"""
        if not path.exists():
            self.initialize()

        text = path.read_text(encoding="utf-8")
        if line in text:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            path.write_text(_update_timestamp(text, now), encoding="utf-8")
            return

        marker = f"## {section}"
        if marker not in text:
            text = text.rstrip() + f"\n\n## {section}\n\n"

        marker_idx = text.index(marker)
        next_section = text.find("\n## ", marker_idx + len(marker))
        if next_section == -1:
            next_section = len(text)

        section_text = text[marker_idx:next_section]
        section_text = section_text.replace("*暂无待跟进事项。*", "")
        section_text = section_text.replace("*暂无待归档事实。*", "").rstrip()
        updated_section = section_text + "\n" + line + "\n"
        new_text = text[:marker_idx] + updated_section + text[next_section:]

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        new_text = _update_timestamp(new_text, now)
        path.write_text(new_text, encoding="utf-8")

    def _append_source_entry(
        self,
        path: Path,
        section: str,
        line: str,
        source_ref: str,
    ) -> bool:
        """用不可见来源标记保证 Markdown 写入在重试时幂等。"""
        if not path.exists():
            self.initialize()
        marker = f"<!-- flow-memory:{source_ref} -->"
        text = path.read_text(encoding="utf-8")
        if marker in text:
            return False
        entry = f"{marker}\n{line}"
        if not section:
            updated = text.rstrip() + f"\n\n{entry}\n"
        else:
            section_marker = f"## {section}"
            if section_marker not in text:
                text = text.rstrip() + f"\n\n{section_marker}\n\n"
            marker_index = text.index(section_marker)
            next_section = text.find("\n## ", marker_index + len(section_marker))
            insert_at = next_section if next_section != -1 else len(text)
            updated = text[:insert_at].rstrip() + f"\n\n{entry}\n" + text[insert_at:]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        path.write_text(_update_timestamp(updated, now), encoding="utf-8")
        return True

    def _migrate_memory_sections(self) -> None:
        """为历史 MEMORY.md 补齐新版分区，同时保留已有内容。"""
        if not self.memory_file.exists():
            return

        text = self.memory_file.read_text(encoding="utf-8")
        updated = text
        for index, (section, description) in enumerate(_MEMORY_SECTION_SPECS):
            marker = f"## {section}"
            if marker in updated:
                continue

            insert_at = len(updated.rstrip())
            for previous_section, _ in reversed(_MEMORY_SECTION_SPECS[:index]):
                previous_marker = f"## {previous_section}"
                previous_index = updated.find(previous_marker)
                if previous_index == -1:
                    continue
                next_section = updated.find(
                    "\n## ",
                    previous_index + len(previous_marker),
                )
                insert_at = next_section if next_section != -1 else len(updated.rstrip())
                break

            new_section = f"\n\n## {section}\n<!-- {description} -->\n"
            updated = updated[:insert_at].rstrip() + new_section + updated[insert_at:]

        if updated == text:
            return

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self.memory_file.write_text(
            _update_timestamp(updated, now),
            encoding="utf-8",
        )
        logger.info("migrated markdown memory sections: %s", self.memory_file)

    def _write_empty_pending(self) -> None:
        """写入新的空缓冲模板；调用方必须已持有写入锁。"""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        self.pending_file.write_text(
            PENDING_TEMPLATE.format(updated_at=now),
            encoding="utf-8",
        )

    def _recover_pending_snapshot(self) -> None:
        """启动时恢复异常中断留下的快照，保证归档至少处理一次。"""
        with self._lock:
            if not self.pending_snapshot_file.exists():
                return
            snapshot_text = self.pending_snapshot_file.read_text(encoding="utf-8")
            current_text = self.pending_file.read_text(encoding="utf-8")
            self.pending_file.write_text(
                _merge_pending_text(current_text, snapshot_text),
                encoding="utf-8",
            )
            self.pending_snapshot_file.unlink()
            logger.warning("已恢复上次异常中断留下的待归档快照")


def _update_timestamp(text: str, timestamp: str) -> str:
    """更新 Markdown 文件头部的时间戳。"""
    return re.sub(
        r"> 最后更新：.*",
        f"> 最后更新：{timestamp}",
        text,
        count=1,
    )


def _section_content(text: str, section: str) -> str:
    """读取指定二级标题中的正文，用于保留已有压缩摘要。"""
    marker = f"## {section}"
    start = text.find(marker)
    if start == -1:
        return ""
    start += len(marker)
    end = text.find("\n## ", start)
    return text[start:end if end != -1 else len(text)].strip()


def _render_recent_context(
    compression: str,
    ongoing_threads: str,
    recent_turns: str,
    updated_at: str,
) -> str:
    """统一渲染近期上下文，避免不同写入路径互相覆盖分区。"""
    return "\n".join(
        [
            "# 近期上下文",
            "",
            "> 最近对话的压缩摘要，用于上下文窗口恢复。",
            f"> 最后更新：{updated_at}",
            "",
            "---",
            "",
            "## 压缩摘要",
            "",
            compression,
            "",
            "## 持续话题",
            "",
            ongoing_threads,
            "",
            "## 最近对话",
            "",
            recent_turns,
            "",
        ]
    )


def _has_pending_entries(text: str) -> bool:
    """判断缓冲中是否存在带标签、可归档的事实。"""
    return any(
        re.match(r"^- \[[^\]]+]\s+\S+", line.strip())
        for line in text.splitlines()
    )


def _merge_pending_text(current: str, snapshot: str) -> str:
    """合并当前缓冲与异常快照，并按隐藏来源标记去除重复条目。"""
    if not current.strip():
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        current = PENDING_TEMPLATE.format(updated_at=now)
    body = _section_content(snapshot, "待归档事实") or _section_content(snapshot, "待处理")
    body = body.replace("*暂无待归档事实。*", "")
    body = body.replace("*暂无待跟进事项。*", "")
    if not body:
        return current
    existing_markers = set(re.findall(r"<!-- flow-memory:[^>]+ -->", current))
    retained_blocks: list[str] = []
    for block in re.split(r"(?=<!-- flow-memory:)", body):
        marker_match = re.match(r"<!-- flow-memory:[^>]+ -->", block)
        if marker_match is not None and marker_match.group(0) in existing_markers:
            continue
        if block.strip():
            retained_blocks.append(block.strip())
    if not retained_blocks:
        return current
    marker = "## 待归档事实"
    if marker not in current:
        current = current.rstrip() + f"\n\n{marker}\n"
    insert_at = current.find("\n## ", current.index(marker) + len(marker))
    if insert_at == -1:
        insert_at = len(current)
    prefix = current[:insert_at].replace("*暂无待归档事实。*", "").rstrip()
    merged = prefix + "\n\n" + "\n\n".join(retained_blocks) + "\n" + current[insert_at:]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return _update_timestamp(merged, now)

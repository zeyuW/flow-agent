"""回合后记忆沉淀：近期上下文、事件归档与待合并画像。"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flow_agent.memory.markdown_store import MarkdownStore
from flow_agent.memory.memorizer import Memorizer
from flow_agent.memory.profile_extractor import ExtractedProfileItem, ProfileExtractor

logger = logging.getLogger(__name__)

_PENDING_TAGS = {
    "identity",
    "preference",
    "key_info",
    "health_long_term",
    "requested_memory",
    "correction",
}


@dataclass(slots=True)
class ConsolidationPayload:
    """一次对话归档提取出的事件和待合并事实。"""

    history_entries: list[str] = field(default_factory=list)
    pending_items: list[tuple[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class ConsolidationResult:
    """一次回合后记忆维护的结果。"""

    recent_turns_refreshed: bool = False
    consolidated: bool = False
    history_count: int = 0
    pending_count: int = 0
    vector_count: int = 0
    compression_updated: bool = False
    reason: str = ""


class ConsolidationLedger:
    """记录已经完成的归档窗口，避免重试时重复处理同一批消息。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS consolidation_writes (
                    source_ref TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                )
                """
            )

    def contains(self, source_ref: str) -> bool:
        """判断指定消息窗口是否已经归档。"""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM consolidation_writes WHERE source_ref = ?",
                (source_ref,),
            ).fetchone()
        return row is not None

    def mark_completed(self, source_ref: str) -> None:
        """标记消息窗口已经完整写入。"""
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO consolidation_writes(source_ref, created_at) VALUES (?, ?)",
                (source_ref, datetime.now(timezone.utc).isoformat()),
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)


class ConversationConsolidator:
    """把稳定用户信息先沉淀到缓冲区，再交给定时归档器处理。"""

    def __init__(
        self,
        *,
        session_manager: Any,
        markdown_store: MarkdownStore,
        memorizer: Memorizer,
        llm_client: Any = None,
        min_new_messages: int = 5,
        recent_turns_limit: int = 8,
    ) -> None:
        self._sessions = session_manager
        self._markdown = markdown_store
        self._memorizer = memorizer
        self._llm_client = llm_client
        self._min_new_messages = max(1, min_new_messages)
        self._recent_turns_limit = max(2, recent_turns_limit)
        self._extractor = ProfileExtractor()
        self._ledger = ConsolidationLedger(markdown_store.consolidation_db)

    def on_turn_committed(self, session_id: str) -> ConsolidationResult:
        """刷新近期对话；满足阈值时归档尚未处理的消息窗口。"""
        session = self._sessions.get_or_create(session_id)
        self._markdown.refresh_recent_turns(
            session.messages,
            limit=self._recent_turns_limit,
        )
        result = ConsolidationResult(recent_turns_refreshed=True)
        start = max(0, session.last_consolidated)
        window = session.messages[start:]
        if len(window) < self._min_new_messages:
            result.reason = "新消息数量未达到归档阈值"
            return result

        source_ref = _source_ref(window)
        if self._ledger.contains(source_ref):
            self._sessions.mark_consolidated(session, len(session.messages))
            result.reason = "消息窗口已经归档"
            return result

        payload = self._extract_payload(window)
        if not payload.history_entries and not payload.pending_items:
            try:
                compression, ongoing_threads = self._build_recent_compression(
                    window,
                    payload,
                )
                self._markdown.update_recent_compression(compression, ongoing_threads)
                result.compression_updated = True
            except Exception:
                # 即使没有可长期沉淀的信息，也尽量保留可恢复的近期上下文。
                logger.exception("近期上下文压缩失败")
            self._sessions.mark_consolidated(session, len(session.messages))
            self._ledger.mark_completed(source_ref)
            result.consolidated = True
            result.reason = "消息窗口没有可长期沉淀的信息"
            return result

        for index, summary in enumerate(payload.history_entries):
            if self._markdown.append_history_entry(
                summary,
                f"{source_ref}:history:{index}",
            ):
                result.history_count += 1

        for index, (tag, content) in enumerate(payload.pending_items):
            item_ref = f"{source_ref}:pending:{index}"
            if self._markdown.append_pending_item(tag, content, item_ref):
                result.pending_count += 1
            memory_type, source_label = _memory_kind_for_pending(tag)
            self._memorizer.memorize(
                memory_type=memory_type,
                summary=content,
                source_ref=f"consolidation:{item_ref}:{source_label}",
            )
            result.vector_count += 1

        try:
            compression, ongoing_threads = self._build_recent_compression(
                window,
                payload,
            )
            self._markdown.update_recent_compression(compression, ongoing_threads)
            result.compression_updated = True
        except Exception:
            # 压缩摘要失败不应影响事件与画像的幂等落盘。
            logger.exception("近期上下文压缩失败")

        self._sessions.mark_consolidated(session, len(session.messages))
        self._ledger.mark_completed(source_ref)
        result.consolidated = True
        result.reason = "归档完成"
        return result

    def _extract_payload(self, messages: list[dict[str, Any]]) -> ConsolidationPayload:
        """优先使用模型提取；模型不可用时退回可预测的规则抽取。"""
        payload = self._extract_with_llm(messages)
        if payload is not None:
            return payload
        return self._extract_with_rules(messages)

    def _extract_with_llm(
        self,
        messages: list[dict[str, Any]],
    ) -> ConsolidationPayload | None:
        if self._llm_client is None:
            return None
        transcript = _format_transcript(messages)
        if not transcript:
            return ConsolidationPayload()
        prompt = f"""从以下用户对话中提取长期记忆候选。

只依据用户消息，不把助手建议、推测或承诺当成用户事实。忽略短期情绪、一次性状态和无长期价值的细节。

返回严格 JSON：
{{
  "history_entries": ["按时间可读的重要事件"],
  "pending_items": [
    {{"tag": "identity|preference|key_info|health_long_term|requested_memory|correction", "content": "以用户为主体的稳定事实"}}
  ]
}}

对话：
{transcript}
"""
        try:
            response = self._llm_client.generate(
                [{"role": "user", "content": prompt}],
            )
            return _parse_payload(response.content)
        except Exception:
            logger.exception("记忆归档模型提取失败，改用规则抽取")
            return None

    def _extract_with_rules(self, messages: list[dict[str, Any]]) -> ConsolidationPayload:
        """在模型不可用时提取明确、低风险的长期事实。"""
        payload = ConsolidationPayload()
        seen_pending: set[tuple[str, str]] = set()
        user_messages = [
            str(message.get("content", "")).strip()
            for message in messages
            if message.get("role") == "user" and str(message.get("content", "")).strip()
        ]
        for text in user_messages:
            for item in self._extractor.extract_memory_items(text):
                tag = _pending_tag_for_item(item)
                if tag is None:
                    continue
                entry = (tag, item.summary)
                if entry not in seen_pending:
                    seen_pending.add(entry)
                    payload.pending_items.append(entry)
        if user_messages:
            focus = "；".join(user_messages[-3:])[:240]
            payload.history_entries.append(f"用户讨论了：{focus}")
        return payload

    def _build_recent_compression(
        self,
        messages: list[dict[str, Any]],
        payload: ConsolidationPayload,
    ) -> tuple[str, str]:
        """为归档窗口生成近期摘要，只把用户原话视为用户事实。"""
        user_messages = [
            str(message.get("content", "")).strip()
            for message in messages
            if message.get("role") == "user" and str(message.get("content", "")).strip()
        ]
        fallback = _fallback_recent_compression(user_messages, payload)
        if self._llm_client is None or not user_messages:
            return fallback
        transcript = "\n".join(f"用户: {text}" for text in user_messages[-8:])
        prompt = f"""根据以下用户消息生成近期上下文摘要。

只能将用户明确表达的内容写成事实；不能把助手建议、推断或承诺写入。内容需简洁，可供后续对话延续。

返回严格 JSON：
{{
  "compression": "用 1-4 条 Markdown 列表总结最近关注点、偏好或待延续内容",
  "ongoing_threads": "用 0-3 条 Markdown 列表描述仍在持续的话题；没有则写 *暂无持续话题。*"
}}

用户消息：
{transcript}
"""
        try:
            response = self._llm_client.generate(
                [{"role": "user", "content": prompt}],
            )
            parsed = _parse_recent_compression(getattr(response, "content", ""))
            return parsed or fallback
        except Exception:
            logger.exception("近期上下文模型压缩失败，改用规则摘要")
            return fallback


def _source_ref(messages: list[dict[str, Any]]) -> str:
    """为消息窗口生成稳定来源标识。"""
    ids = [str(message.get("id", "")).strip() for message in messages]
    stable_ids = [item for item in ids if item]
    if stable_ids:
        return json.dumps(stable_ids, ensure_ascii=False, separators=(",", ":"))
    body = "\n".join(
        f"{message.get('role', '')}:{message.get('content', '')}" for message in messages
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:24]


def _format_transcript(messages: list[dict[str, Any]]) -> str:
    """构造仅含用户与助手正文的归档输入。"""
    lines: list[str] = []
    for message in messages:
        role = str(message.get("role", ""))
        if role not in {"user", "assistant"}:
            continue
        content = str(message.get("content", "")).strip()
        if content:
            label = "用户" if role == "user" else "助手"
            lines.append(f"{label}: {content}")
    return "\n".join(lines)


def _parse_payload(text: str) -> ConsolidationPayload | None:
    """解析并校验模型返回的归档 JSON。"""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    history_entries = [
        str(item.get("summary", "")).strip()
        if isinstance(item, dict)
        else str(item).strip()
        for item in value.get("history_entries", [])
        if isinstance(item, str | dict)
    ]
    pending_items: list[tuple[str, str]] = []
    for item in value.get("pending_items", []):
        if not isinstance(item, dict):
            continue
        tag = str(item.get("tag", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if tag in _PENDING_TAGS and content:
            pending_items.append((tag, content))
    return ConsolidationPayload(
        history_entries=[item for item in history_entries if item],
        pending_items=pending_items,
    )


def _pending_tag_for_item(item: ExtractedProfileItem) -> str | None:
    """将结构化抽取类型映射为待归档标签。"""
    if item.memory_type == "preference":
        return "preference"
    if item.memory_type == "fact":
        return "identity" if item.source_label == "identity" else "requested_memory"
    if item.memory_type in {"need", "task"}:
        return "requested_memory"
    return None


def _memory_kind_for_pending(tag: str) -> tuple[str, str]:
    """将待归档标签映射到向量记忆类型。"""
    if tag == "preference":
        return "preference", "preference"
    if tag == "identity":
        return "fact", "identity"
    if tag in {"key_info", "health_long_term", "correction"}:
        return "fact", "fact"
    return "need", "pending"


def _parse_recent_compression(text: str) -> tuple[str, str] | None:
    """解析模型输出的近期摘要 JSON，并拒绝空字段。"""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    compression = str(value.get("compression", "")).strip()
    ongoing_threads = str(value.get("ongoing_threads", "")).strip()
    if not compression:
        return None
    return compression, ongoing_threads or "*暂无持续话题。*"


def _fallback_recent_compression(
    user_messages: list[str],
    payload: ConsolidationPayload,
) -> tuple[str, str]:
    """在模型不可用时，以最近用户消息生成保守且可读的上下文。"""
    if not user_messages:
        return "*尚未生成近期摘要。*", "*暂无持续话题。*"
    recent = "；".join(user_messages[-3:])[:300]
    compression = f"- 最近讨论：{recent}"
    pending = [content for _tag, content in payload.pending_items[:3]]
    if pending:
        ongoing = "\n".join(f"- {item}" for item in pending)
    else:
        ongoing = "- 等待用户继续当前话题。"
    return compression, ongoing


@dataclass(slots=True)
class OptimizerResult:
    """一次定时画像归档的结果。"""

    updated: bool = False
    merged_count: int = 0
    reason: str = ""


class MemoryOptimizer:
    """把待归档事实批量合并到稳定用户画像，降低长期档案变更频率。"""

    def __init__(self, markdown_store: MarkdownStore, llm_client: Any = None) -> None:
        self._markdown = markdown_store
        self._llm_client = llm_client

    def run_once(self) -> OptimizerResult:
        """以快照事务归档当前待处理事实，避免并发写入或异常造成丢失。"""
        snapshot = self._markdown.snapshot_pending()
        if snapshot is None:
            return OptimizerResult(reason="没有待归档事实")

        try:
            entries = _parse_pending(snapshot.read_text(encoding="utf-8"))
            if not entries:
                self._markdown.commit_pending_snapshot(snapshot)
                return OptimizerResult(reason="快照中没有可归档事实")

            optimized = self._optimize_with_llm(entries)
            if optimized is None:
                self._merge_deterministically(entries)
            else:
                memory_text, self_text = optimized
                self._markdown.write_memory(memory_text)
                if self_text:
                    self._markdown.write_self(self_text)

            self._markdown.commit_pending_snapshot(snapshot)
            return OptimizerResult(
                updated=True,
                merged_count=len(entries),
                reason="长期画像归档完成",
            )
        except Exception:
            logger.exception("画像归档失败，已恢复待归档快照")
            self._markdown.rollback_pending_snapshot(snapshot)
            return OptimizerResult(reason="画像归档失败，待归档事实已保留")

    def _merge_deterministically(self, entries: list[tuple[str, str]]) -> None:
        """模型不可用时按标签合并，保持行为可预测且可恢复。"""
        for tag, content in entries:
            memory_type, source_label = _memory_section_for_tag(tag)
            self._markdown.append_memory_item(
                memory_type,
                content,
                source_label=source_label,
            )
        self._update_self(entries)

    def _optimize_with_llm(
        self,
        entries: list[tuple[str, str]],
    ) -> tuple[str, str] | None:
        """让模型处理重复与更正；解析失败时由确定性合并安全兜底。"""
        if self._llm_client is None:
            return None
        pending = "\n".join(f"- [{tag}] {content}" for tag, content in entries)
        prompt = f"""将待归档用户信息合并到长期画像。

只使用提供的待归档事实，不要编造信息。保留原有事实；重复时去重；遇到 correction 时，应以更正后的信息替换冲突条目。保持内容紧凑，且必须保留所有二级标题。

返回严格 JSON：
{{
  "memory_markdown": "完整的 MEMORY.md 内容",
  "self_markdown": "完整的 SELF.md 内容；若不需要修改则原样返回"
}}

当前长期画像：
{self._markdown.read_memory()}

当前协作认知：
{self._markdown.read_self()}

待归档事实：
{pending}
"""
        try:
            response = self._llm_client.generate(
                [{"role": "user", "content": prompt}],
            )
        except Exception:
            logger.exception("画像归档模型调用失败，改用确定性合并")
            return None
        return _parse_optimized_markdown(getattr(response, "content", ""))

    def _update_self(self, entries: list[tuple[str, str]]) -> None:
        """仅在用户明确记忆请求时更新协作关系描述。"""
        requested = [content for tag, content in entries if tag == "requested_memory"]
        if not requested:
            return
        current = self._markdown.read_self()
        marker = "## 对用户的理解"
        if marker not in current:
            return
        line = f"- 用户明确希望助手记住：{requested[-1]}"
        if line in current:
            return
        index = current.index(marker) + len(marker)
        next_section = current.find("\n## ", index)
        insert_at = next_section if next_section != -1 else len(current)
        updated = current[:insert_at].rstrip() + f"\n{line}\n" + current[insert_at:]
        self._markdown.write_self(updated)


class MemoryOptimizerLoop:
    """以固定间隔运行画像归档器的后台线程。"""

    def __init__(self, optimizer: MemoryOptimizer, interval_seconds: int) -> None:
        self._optimizer = optimizer
        self._interval_seconds = max(60, interval_seconds)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """启动定时归档线程；重复调用不会重复创建线程。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="memory-optimizer",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """请求停止定时归档线程。"""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                result = self._optimizer.run_once()
                logger.info(
                    "定时画像归档完成：updated=%s merged=%d reason=%s",
                    result.updated,
                    result.merged_count,
                    result.reason,
                )
            except Exception:
                logger.exception("定时画像归档失败")
            self._stop_event.wait(self._interval_seconds)


def _parse_pending(text: str) -> list[tuple[str, str]]:
    """读取 PENDING.md 中的带标签事实。"""
    entries: list[tuple[str, str]] = []
    pattern = re.compile(r"^- \[([^\]]+)]\s+(.+)$")
    for line in text.splitlines():
        match = pattern.match(line.strip())
        if match is None:
            continue
        tag = match.group(1).strip().lower()
        content = match.group(2).strip()
        if tag and content:
            entries.append((tag, content))
    return entries


def _memory_section_for_tag(tag: str) -> tuple[str, str]:
    """将待归档标签映射到长期档案分区。"""
    if tag == "identity":
        return "fact", "identity"
    if tag == "preference":
        return "preference", "preference"
    if tag in {"key_info", "health_long_term", "correction"}:
        return "fact", "fact"
    return "need", "pending"


def _parse_optimized_markdown(text: str) -> tuple[str, str] | None:
    """校验模型返回的完整档案，避免不完整结果覆盖已有记忆。"""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw).strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("画像归档模型未返回有效 JSON，改用确定性合并")
        return None
    if not isinstance(value, dict):
        return None
    memory_text = str(value.get("memory_markdown", "")).strip()
    self_text = str(value.get("self_markdown", "")).strip()
    required_memory_sections = (
        "身份信息",
        "事实信息",
        "偏好设置",
        "需求记录",
        "目标与计划",
        "约束限制",
    )
    if not memory_text or not all(
        f"## {section}" in memory_text for section in required_memory_sections
    ):
        logger.warning("画像归档模型返回的长期档案缺少必要分区，改用确定性合并")
        return None
    if self_text and "## 对用户的理解" not in self_text:
        logger.warning("画像归档模型返回的协作认知缺少必要分区，忽略该部分")
        self_text = ""
    return memory_text, self_text

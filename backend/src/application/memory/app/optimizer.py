"""长期画像优化器：消费待归档事实并更新稳定画像。"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from application.memory.infra.markdown_store import MarkdownStore
from application.capabilities.llm.client import llm_stage
from infra.telemetry import trace_scope

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OptimizerResult:
    """一次定时画像归档的结果。"""

    updated: bool = False
    merged_count: int = 0
    reason: str = ""


class MemoryOptimizer:
    """把待归档事实批量合并到稳定用户画像。"""

    def __init__(self, markdown_store: MarkdownStore, llm_client: Any = None) -> None:
        self._markdown = markdown_store
        self._llm_client = llm_client

    def run_once(self) -> OptimizerResult:
        """以快照事务归档当前待处理事实，避免异常造成丢失。"""

        snapshot = self._markdown.snapshot_pending()
        if snapshot is None:
            return OptimizerResult(reason="没有待归档事实")
        try:
            entries = _parse_pending(snapshot.read_text(encoding="utf-8"))
            if not entries:
                self._markdown.commit_pending_snapshot(snapshot)
                return OptimizerResult(reason="快照中没有可归档事实")
            with trace_scope(f"memory-{uuid4().hex[:12]}"), llm_stage("memory"):
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
            self._markdown.append_memory_item(memory_type, content, source_label=source_label)
        self._update_self(entries)

    def _optimize_with_llm(self, entries: list[tuple[str, str]]) -> tuple[str, str] | None:
        """让模型处理重复与更正；解析失败时安全回退。"""

        if self._llm_client is None:
            return None
        pending = "\n".join(f"- [{tag}] {content}" for tag, content in entries)
        prompt = f"""将待归档用户信息合并到长期画像。

只使用提供的待归档事实，不要编造信息。保留原有事实；重复时去重；遇到 correction 时，以更正后的信息替换冲突条目。保持内容紧凑，且必须保留所有二级标题。

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
            response = self._llm_client.generate([{"role": "user", "content": prompt}])
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
        self._markdown.write_self(
            current[:insert_at].rstrip() + f"\n{line}\n" + current[insert_at:]
        )


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
        self._thread = threading.Thread(target=self._run, name="memory-optimizer", daemon=True)
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
        if match is not None:
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
        "身份信息", "事实信息", "偏好设置", "需求记录", "目标与计划", "约束限制",
    )
    if not memory_text or not all(f"## {section}" in memory_text for section in required_memory_sections):
        logger.warning("画像归档模型返回的长期档案缺少必要分区，改用确定性合并")
        return None
    if self_text and "## 对用户的理解" not in self_text:
        logger.warning("画像归档模型返回的协作认知缺少必要分区，忽略该部分")
        self_text = ""
    return memory_text, self_text

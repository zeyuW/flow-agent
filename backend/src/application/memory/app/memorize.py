"""memorize 工具：LLM 调用此工具显式写入长期记忆。

实现 spec 4f：LLM 通过此工具写入新记忆，自动 supersede 高相似旧条目。
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

from application.memory.infra.markdown_store import MarkdownStore
from application.memory.app.memorizer import Memorizer
from application.capabilities.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MemorizeTool:
    """memorize 工具：显式写入长期记忆。

    写入时自动检测相似旧条目，如果相似度超过阈值则自动 supersede。
    """

    memorizer: Memorizer
    # 具体存储由组装层注入，应用层只依赖其所需的方法契约。
    store: Any
    markdown_store: MarkdownStore | None = None
    supersede_threshold: float = 0.85

    @property
    def name(self) -> str:
        return "memorize"

    @property
    def description(self) -> str:
        return (
            "将重要信息写入长期记忆。用于记住用户的事实、偏好、需求、任务、规则和事件。"
            "参数: memory_type (procedure/preference/event/fact/need/task), summary (记忆摘要)"
        )

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "memory_type": {
                    "type": "string",
                    "enum": ["procedure", "preference", "event", "fact", "need", "task"],
                    "description": "记忆类型",
                },
                "summary": {
                    "type": "string",
                    "description": "记忆摘要，简洁描述要记住的内容",
                },
                "emotional_weight": {
                    "type": "number",
                    "description": "情感权重，1.0 为默认",
                    "default": 1.0,
                },
            },
            "required": ["memory_type", "summary"],
        }

    def __call__(self, payload: str) -> str:
        """执行记忆写入。

        Args:
            payload: JSON 字符串，包含 memory_type, summary, emotional_weight。

        Returns:
            JSON 字符串，包含写入结果。
        """
        try:
            args = json.loads(payload) if isinstance(payload, str) else payload
        except json.JSONDecodeError:
            return json.dumps({"error": "invalid JSON payload"}, ensure_ascii=False)

        memory_type = args.get("memory_type", "")
        summary = args.get("summary", "")
        emotional_weight = args.get("emotional_weight", 1.0)

        if not memory_type or not summary:
            return json.dumps({"error": "memory_type and summary are required"}, ensure_ascii=False)

        # spec 4f: 写入新记忆并自动 supersede 高相似旧条目
        supersede_ids = self._check_supersede(memory_type, summary)
        if supersede_ids:
            self.store.mark_superseded_batch(supersede_ids)
            logger.info(
                "已替换 %d 条旧记忆，类型=%s",
                len(supersede_ids),
                memory_type,
            )

        result = self.memorizer.memorize(
            memory_type=memory_type,
            summary=summary,
            source_ref=f"memorize_tool:{memory_type}:{summary[:40]}",
            emotional_weight=emotional_weight,
        )
        self._sync_markdown(memory_type, summary)

        return json.dumps(
            {
                "item_id": result.item_id,
                "content_hash": result.content_hash,
                "was_duplicate": result.was_duplicate,
                "reinforcement": result.reinforcement,
                "superseded_count": len(supersede_ids) if supersede_ids else 0,
            },
            ensure_ascii=False,
            indent=2,
        )

    def _sync_markdown(self, memory_type: str, summary: str) -> None:
        """同步显式写入的长期记忆到可读档案。"""
        if self.markdown_store is None:
            return
        try:
            self.markdown_store.append_memory_item(memory_type, summary)
        except Exception:
            # 可读档案更新失败不能影响已经完成的向量记忆写入。
            logger.exception("同步记忆 Markdown 档案失败")

    def _check_supersede(
        self,
        memory_type: str,
        summary: str,
    ) -> list[str]:
        """检查是否存在高相似度的旧记忆需要 supersede（spec 4f）。

        通过内存中的余弦相似度检查（不需要 embedding API 调用）。
        """
        active = self.store.list_active(memory_type=memory_type)
        if not active:
            return []

        to_supersede: list[str] = []

        summary_tokens = set(summary.lower().split())
        if not summary_tokens:
            return []

        for item in active:
            item_tokens = set(item.summary.lower().split())
            if not item_tokens:
                continue
            overlap = len(summary_tokens & item_tokens) / len(summary_tokens)
            if overlap >= self.supersede_threshold:
                to_supersede.append(item.id)

        return to_supersede


# 兼容适配器
class MemorizeToolAdapter:
    """将 MemorizeTool 适配到 ToolProtocol 接口。"""

    def __init__(self, tool: MemorizeTool) -> None:
        self.tool = tool

    @property
    def name(self) -> str:
        return self.tool.name

    @property
    def description(self) -> str:
        return self.tool.description

    @property
    def parameters(self) -> dict[str, Any]:
        return self.tool.schema

    @property
    def input_schema(self) -> dict[str, Any]:
        return self.tool.schema

    def execute(self, **kwargs) -> str:
        payload = json.dumps(kwargs)
        return self.tool(payload)

    def run(self, tool_input: dict[str, str]) -> ToolResult:
        """按 ToolRegistry 协议执行记忆写入。"""
        content = self.execute(**tool_input)
        return ToolResult(ok=_json_result_ok(content), content=content)

    def to_openai_function(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.tool.schema,
            },
        }


def _json_result_ok(content: str) -> bool:
    """根据工具 JSON 结果判断是否成功。"""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return False
    return not (isinstance(data, dict) and data.get("error"))

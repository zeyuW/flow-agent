"""recall_memory 工具：LLM 调用此工具查询向量记忆。

实现 spec 3a：Agent 通过此工具从记忆向量库中检索相关信息。
支持两种查询模式：
- answer: 查询相关记忆用于回答问题
- timeline: 查询时间线记忆（历史事件）
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

from flow_agent.memory.memory_engine import MemoryEngine, MemoryQuery
from flow_agent.tools.protocol import ToolProtocol

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RecallMemoryTool:
    """recall_memory 工具：从长期记忆中检索相关信息。"""

    engine: MemoryEngine

    @property
    def name(self) -> str:
        return "recall_memory"

    @property
    def description(self) -> str:
        return (
            "从长期记忆库中检索相关记忆。用于查询用户的偏好、规则、历史事件等信息。"
            "参数: query (查询文本), intent (可选: answer/timeline/profile/rule), "
            "max_items (返回条数, 默认8)"
        )

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "要检索的查询文本",
                },
                "intent": {
                    "type": "string",
                    "enum": ["answer", "timeline", "profile", "rule"],
                    "description": "查询意图",
                    "default": "answer",
                },
                "max_items": {
                    "type": "integer",
                    "description": "最大返回条数",
                    "default": 8,
                },
                "memory_type": {
                    "type": "string",
                    "enum": ["procedure", "preference", "event", "fact"],
                    "description": "记忆类型过滤",
                },
            },
            "required": ["query"],
        }

    def __call__(self, payload: str) -> str:
        """执行记忆检索。

        Args:
            payload: JSON 字符串，包含 query, intent, max_items, memory_type。

        Returns:
            JSON 字符串，包含检索结果。
        """
        try:
            args = json.loads(payload) if isinstance(payload, str) else payload
        except json.JSONDecodeError:
            return json.dumps({"error": "invalid JSON payload"}, ensure_ascii=False)

        query_text = args.get("query", "")
        if not query_text:
            return json.dumps({"error": "query is required"}, ensure_ascii=False)

        q = MemoryQuery(
            text=query_text,
            intent=args.get("intent", "answer"),
            max_items=args.get("max_items", 8),
            memory_type=args.get("memory_type"),
        )

        result = self.engine.query(q)

        items = []
        for hit in result.hits:
            items.append({
                "id": hit.item.id,
                "type": hit.item.memory_type,
                "summary": hit.item.summary,
                "score": round(hit.score, 4),
                "reinforcement": hit.item.reinforcement,
                "status": hit.item.status,
            })

        return json.dumps(
            {
                "query": result.query.text,
                "intent": result.query.intent,
                "total_active": result.total_active,
                "found": len(items),
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        )


# 为了兼容现有 ToolProtocol，提供一个适配器
class RecallMemoryToolAdapter:
    """将 RecallMemoryTool 适配到 ToolProtocol 接口。"""

    def __init__(self, tool: RecallMemoryTool) -> None:
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

    def execute(self, **kwargs) -> str:
        payload = json.dumps(kwargs)
        return self.tool(payload)

    def to_openai_function(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.tool.schema,
            },
        }

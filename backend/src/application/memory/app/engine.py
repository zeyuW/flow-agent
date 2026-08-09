"""记忆引擎：查询路由 + 检索执行 + 结果聚合。

实现 spec 3a-3b：
- 3a: recall_memory 工具的查询入口（通过 query() 方法）
- 3b: 委托给检索器执行双通道检索
"""

import logging
from dataclasses import dataclass, field
from typing import Protocol

from application.memory.domain.models import RetrievalHit
from application.memory.infra.retriever import DualChannelRetriever
from application.memory.infra.vector_store import MemoryStore
from application.memory.infra.embedder import Embedder

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MemoryQuery:
    """记忆查询对象。"""

    text: str
    intent: str = "answer"  # answer / timeline / profile / rule
    max_items: int = 10
    memory_type: str | None = None


@dataclass(slots=True)
class MemoryQueryResult:
    """记忆查询结果。"""

    query: MemoryQuery
    hits: list[RetrievalHit] = field(default_factory=list)
    total_active: int = 0


class MemoryEngine:
    """记忆引擎：统一查询入口。

    支持多种查询意图：
    - answer: 一般问答（默认），返回最相关的记忆
    - timeline: 时间线查询，返回事件记忆
    - profile: 查询用户画像相关记忆，不强制限定单一类型
    - rule: 查询规则/约束类记忆
    """

    def __init__(
        self,
        store: MemoryStore,
        embedder: Embedder,
        retriever: DualChannelRetriever | None = None,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.retriever = retriever or DualChannelRetriever(store, embedder)

    def query(self, q: MemoryQuery) -> MemoryQueryResult:
        """执行记忆查询（spec 3b, 3c）。

        根据查询意图路由检索策略：
        - timeline: 只检索 event 类型记忆
        - profile/rule: 检索对应的记忆类型
        - answer: 全类型检索
        """
        mt = q.memory_type
        if q.intent == "timeline":
            mt = mt or "event"
        elif q.intent == "rule":
            mt = mt or "procedure"

        hits = self.retriever.retrieve(
            query=q.text,
            top_k=q.max_items,
            memory_type=mt,
        )
        total = self.store.count_active()
        return MemoryQueryResult(query=q, hits=hits, total_active=total)

    def query_text(
        self,
        text: str,
        intent: str = "answer",
        max_items: int = 10,
        memory_type: str | None = None,
    ) -> MemoryQueryResult:
        """快捷查询：直接从文本查询。"""
        return self.query(MemoryQuery(
            text=text,
            intent=intent,
            max_items=max_items,
            memory_type=memory_type,
        ))

    def retrieve_for_prompt(
        self,
        text: str,
        max_items: int = 8,
        max_chars: int = 2000,
    ) -> str:
        """为提示词注入检索记忆（spec 3f）。

        返回格式化的记忆块，适合直接插入到 LLM 提示词中。
        """
        result = self.query_text(text, max_items=max_items)
        if not result.hits:
            return ""

        from application.memory.app.injection import format_injection_block

        return format_injection_block(result.hits, max_chars=max_chars)
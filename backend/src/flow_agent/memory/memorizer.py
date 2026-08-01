"""记忆写入组件：embedding + 去重 + reinforcement + supersede。

负责将原始文本转换为向量化记忆条目并写入 MemoryStore，
自动处理去重（content_hash）和强化计数。
"""

import logging
from dataclasses import dataclass

from flow_agent.memory.embedder import Embedder
from flow_agent.memory.vector_store import MemoryStore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MemorizeResult:
    """写入记忆的结果。"""

    item_id: str
    content_hash: str
    was_duplicate: bool
    reinforcement: int


class Memorizer:
    """记忆写入器：将文本转换为向量并持久化到 MemoryStore。

    流程：
    1. 计算 content_hash 去重检查
    2. 如果已存在 → reinforcement+1
    3. 如果已存在且 superseded → 重新激活
    4. 如果不存在 → embedding → 写入
    """

    def __init__(self, store: MemoryStore, embedder: Embedder) -> None:
        self.store = store
        self.embedder = embedder

    def memorize(
        self,
        memory_type: str,
        summary: str,
        source_ref: str = "",
        emotional_weight: float = 1.0,
    ) -> MemorizeResult:
        """写入一条记忆。"""
        # 先检查是否已存在（只用 content_hash，不走 embedding 以节省成本）
        from flow_agent.memory.vector_store import _compute_content_hash

        content_hash = _compute_content_hash(summary, memory_type)
        existing = self.store.search_by_source_ref(source_ref) if source_ref else []

        # 生成 embedding（新条目需要）
        embedding = self.embedder.embed(summary)

        item = self.store.write(
            memory_type=memory_type,
            summary=summary,
            embedding=embedding,
            source_ref=source_ref,
            emotional_weight=emotional_weight,
        )

        was_dup = item.reinforcement > 1 or any(e.content_hash == content_hash for e in existing)
        return MemorizeResult(
            item_id=item.id,
            content_hash=content_hash,
            was_duplicate=was_dup,
            reinforcement=item.reinforcement,
        )

    def memorize_batch(
        self,
        items: list[dict],
    ) -> list[MemorizeResult]:
        """批量写入记忆条目。

        Args:
            items: [{"memory_type": "event", "summary": "...", "source_ref": "...", "emotional_weight": 1.0}, ...]
        """
        results: list[MemorizeResult] = []
        for item in items:
            result = self.memorize(
                memory_type=item.get("memory_type", "fact"),
                summary=item.get("summary", ""),
                source_ref=item.get("source_ref", ""),
                emotional_weight=item.get("emotional_weight", 1.0),
            )
            results.append(result)
        return results

    def force_write(
        self,
        memory_type: str,
        summary: str,
        embedding: list[float] | None = None,
        source_ref: str = "",
        emotional_weight: float = 1.0,
    ) -> MemorizeResult:
        """强制写入（即使内容重复也创建新条目）。"""
        if embedding is None:
            embedding = self.embedder.embed(summary)
        from flow_agent.memory.vector_store import _compute_content_hash

        content_hash = _compute_content_hash(summary, memory_type)
        item = self.store.write(
            memory_type=memory_type,
            summary=summary,
            embedding=embedding,
            source_ref=source_ref,
            emotional_weight=emotional_weight,
        )
        return MemorizeResult(
            item_id=item.id,
            content_hash=content_hash,
            was_duplicate=False,
            reinforcement=item.reinforcement,
        )

"""双通道记忆检索器：向量检索 + 关键词检索 + RRF 融合。

实现 spec 3c-3e：
- 3c: 检索执行逻辑（路由到向量和关键词两通道）
- 3d: 向量检索通道（ANN 余弦相似度）
- 3e: RRF 融合（Reciprocal Rank Fusion）
"""

import logging
import math
from typing import Protocol

from application.memory.infra.embedder import Embedder
from application.memory.domain.models import MemoryItem, RetrievalHit
from application.memory.infra.vector_store import MemoryStore

logger = logging.getLogger(__name__)


class MemoryRetrieverProtocol(Protocol):
    """记忆检索器接口。"""

    def retrieve(self, query: str, top_k: int = 10) -> list[RetrievalHit]:
        ...


class DualChannelRetriever:
    """双通道记忆检索器：向量 + 关键词 + RRF 融合。

    向量通道：将 query embedding 后与所有 active 记忆的 embedding
              计算余弦相似度，返回 top-N 候选。

    关键词通道：使用 TF-IDF 风格的关键词重叠评分。

    RRF 融合：将两个通道的排序位置通过 Reciprocal Rank Fusion 合并，
             平衡语义相似度和字面匹配度。
    """

    def __init__(
        self,
        store: MemoryStore,
        embedder: Embedder,
        *,
        vector_top_k: int = 20,
        keyword_top_k: int = 15,
        rrf_k: int = 60,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self.vector_top_k = vector_top_k
        self.keyword_top_k = keyword_top_k
        self.rrf_k = rrf_k

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        memory_type: str | None = None,
    ) -> list[RetrievalHit]:
        """执行双通道检索并返回 RRF 融合后的结果。

        Args:
            query: 查询文本。
            top_k: 返回前 K 个结果。
            memory_type: 可选过滤记忆类型。

        Returns:
            RRF 融合排序后的检索结果列表。
        """
        if not query.strip():
            return []

        all_items = self.store.list_active(memory_type=memory_type)
        if not all_items:
            return []

        # 通道 1：向量检索（spec 3d）
        query_emb = self.embedder.embed(query)
        vector_ranked = self._vector_search(query_emb, all_items, self.vector_top_k)

        # 通道 2：关键词检索
        keyword_ranked = self._keyword_search(query, all_items, self.keyword_top_k)

        # RRF 融合（spec 3e）
        fused = self._rrf_fuse(vector_ranked, keyword_ranked, top_k)
        return fused

    def _vector_search(
        self,
        query_emb: list[float],
        items: list[MemoryItem],
        top_k: int,
    ) -> list[tuple[MemoryItem, float, int]]:
        """向量检索通道：余弦相似度排序（spec 3d）。"""
        scored: list[tuple[MemoryItem, float]] = []
        query_norm = _l2_norm(query_emb)
        if query_norm == 0.0:
            return []

        for item in items:
            if not item.embedding:
                continue
            item_norm = _l2_norm(item.embedding)
            if item_norm == 0.0:
                continue
            cosine = _cosine_similarity(query_emb, item.embedding, query_norm, item_norm)
            # 加权：reinforcement 和 emotional_weight 影响排序
            boost = math.log(1 + item.reinforcement) / 5.0
            weighted = cosine * (1.0 + boost * item.emotional_weight)
            scored.append((item, weighted))

        scored.sort(key=lambda x: x[1], reverse=True)
        results: list[tuple[MemoryItem, float, int]] = []
        for rank, (item, score) in enumerate(scored[:top_k]):
            results.append((item, score, rank + 1))
        return results

    def _keyword_search(
        self,
        query: str,
        items: list[MemoryItem],
        top_k: int,
    ) -> list[tuple[MemoryItem, float, int]]:
        """关键词检索通道：TF-IDF 风格关键词重叠评分。"""
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[MemoryItem, float]] = []
        for item in items:
            item_tokens = _tokenize(item.summary)
            if not item_tokens:
                continue
            overlap = len(query_tokens & item_tokens) / len(query_tokens)
            # reinforcement 加权
            boost = math.log(1 + item.reinforcement) / 5.0
            weighted = overlap * (1.0 + boost)
            if weighted > 0:
                scored.append((item, weighted))

        scored.sort(key=lambda x: x[1], reverse=True)
        results: list[tuple[MemoryItem, float, int]] = []
        for rank, (item, score) in enumerate(scored[:top_k]):
            results.append((item, score, rank + 1))
        return results

    def _rrf_fuse(
        self,
        vector_results: list[tuple[MemoryItem, float, int]],
        keyword_results: list[tuple[MemoryItem, float, int]],
        top_k: int,
    ) -> list[RetrievalHit]:
        """RRF 融合两个通道的结果（spec 3e）。

        RRF 公式：score(item) = sum(1 / (k + rank)) for each channel
        其中 k = rrf_k，rank 从 1 开始。
        """
        rrf_scores: dict[int, tuple[MemoryItem, float, float]] = {}
        # item_id -> (item, vector_score, keyword_score)

        for item, score, rank in vector_results:
            rrf_scores[item.id] = (item, 1.0 / (self.rrf_k + rank), 0.0)

        for item, score, rank in keyword_results:
            ks = 1.0 / (self.rrf_k + rank)
            if item.id in rrf_scores:
                prev_item, vs, _ = rrf_scores[item.id]
                rrf_scores[item.id] = (prev_item, vs, ks)
            else:
                rrf_scores[item.id] = (item, 0.0, ks)

        fused: list[RetrievalHit] = []
        for item_id, (item, vs, ks) in rrf_scores.items():
            fused_score = vs + ks
            fused.append(RetrievalHit(
                item=item,
                score=fused_score,
                vector_score=vs,
                keyword_score=ks,
            ))

        fused.sort(key=lambda h: h.score, reverse=True)
        return fused[:top_k]


def _cosine_similarity(
    a: list[float],
    b: list[float],
    a_norm: float,
    b_norm: float,
) -> float:
    """纯 Python 余弦相似度。"""
    dot = sum(x * y for x, y in zip(a, b))
    return max(0.0, min(1.0, dot / (a_norm * b_norm)))


def _l2_norm(vec: list[float]) -> float:
    return math.sqrt(sum(v * v for v in vec))


def _tokenize(text: str) -> set[str]:
    """简单分词：提取中文/英文/数字 token。"""
    import re
    token_re = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
    tokens: set[str] = set()
    for t in token_re.findall(text):
        t_lower = t.lower()
        tokens.add(t_lower)
        # 对中文做字符级补充
        if all(0x4E00 <= ord(ch) <= 0x9FFF for ch in t_lower) and len(t_lower) > 1:
            tokens.update(t_lower)
        return tokens

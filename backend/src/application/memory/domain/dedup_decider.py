"""记忆质量控制去重决策器。"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class DedupDecision(str, Enum):
    SKIP = "skip"
    CREATE = "create"
    NONE = "none"


class MemoryAction(str, Enum):
    MERGE = "merge"
    DELETE = "delete"


@dataclass
class ExistingAction:
    item_id: str
    summary: str
    action: MemoryAction
    reason: str = ""


@dataclass
class DedupResult:
    decision: DedupDecision
    candidate_summary: str
    candidate_type: str
    similar_items: list[dict]
    actions: list[ExistingAction] = field(default_factory=list)
    reason: str = ""
    query_vector: list[float] | None = None


class DedupDecider:
    """两阶段去重：向量预筛选 + LLM 决策。"""

    def __init__(
        self,
        store,
        embedder,
        llm_client: Any,
        model: str,
        similarity_threshold: float = 0.45,
        batch_dedup_threshold: float = 0.90,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._llm_client = llm_client
        self._model = model
        self._similarity_threshold = similarity_threshold
        self._batch_dedup_threshold = batch_dedup_threshold
        self._max_similar_to_llm = 5

    async def decide(
        self,
        candidate: dict,
        *,
        batch_vecs: list[tuple[list[float], dict]] | None = None,
    ) -> DedupResult:
        """根据去重决定是否跳过或创建记忆。"""
        summary = (candidate.get("summary") or "").strip()
        mtype = candidate.get("memory_type", "procedure")

        query_vec = await self._embedder.embed(summary)

        similar = self._find_similar(
            query_vec=query_vec,
            memory_type=mtype,
            source_ref=candidate.get("source_ref", ""),
        )

        if not similar:
            return DedupResult(
                decision=DedupDecision.CREATE,
                candidate_summary=summary,
                candidate_type=mtype,
                similar_items=[],
                query_vector=query_vec,
            )

        # 批量去重检查
        if batch_vecs:
            batch_similar = self._find_batch_similar(query_vec, batch_vecs)
            if batch_similar:
                return DedupResult(
                    decision=DedupDecision.SKIP,
                    candidate_summary=summary,
                    candidate_type=mtype,
                    similar_items=[batch_similar],
                    reason="batch_deduplication",
                    query_vector=query_vec,
                )

        # 对相似项进行 LLM 决策
        top_similar = similar[: self._max_similar_to_llm]
        decision, actions = await self._llm_decide(summary, mtype, top_similar)

        return DedupResult(
            decision=decision,
            candidate_summary=summary,
            candidate_type=mtype,
            similar_items=top_similar,
            actions=actions,
            query_vector=query_vec,
        )

    def _find_similar(
        self,
        query_vec: list[float],
        memory_type: str,
        source_ref: str,
    ) -> list[dict]:
        """在存储中查找相似项。"""
        results = self._store.vector_search(
            query_embedding=query_vec,
            top_k=10,
            memory_type=memory_type,
            score_threshold=self._similarity_threshold,
        )

        similar = []
        for item, score in results:
            if item.source_ref == source_ref:
                continue  # 跳过相同来源
            similar.append(
                {
                    "id": str(item.id),
                    "summary": item.summary,
                    "memory_type": item.memory_type,
                    "score": score,
                }
            )

        return similar

    def _find_batch_similar(
        self,
        query_vec: list[float],
        batch_vecs: list[tuple[list[float], dict]],
    ) -> dict | None:
        """在当前批次中查找相似项。"""
        import numpy as np

        query_vec_np = np.array(query_vec, dtype=np.float32)
        query_vec_np = query_vec_np / np.linalg.norm(query_vec_np)

        for vec, item in batch_vecs:
            vec_np = np.array(vec, dtype=np.float32)
            vec_np = vec_np / np.linalg.norm(vec_np)
            score = float(np.dot(query_vec_np, vec_np))
            if score >= self._batch_dedup_threshold:
                return {
                    "id": item.get("id", "batch"),
                    "summary": item.get("summary", ""),
                    "memory_type": item.get("memory_type", ""),
                    "score": score,
                }
        return None

    async def _llm_decide(
        self,
        summary: str,
        memory_type: str,
        similar_items: list[dict],
    ) -> tuple[DedupDecision, list[ExistingAction]]:
        """使用 LLM 决定去重操作。"""
        if not similar_items:
            return DedupDecision.CREATE, []

        # 构建提示词
        similar_text = "\n".join(
            f"- [{item['id']}] {item['summary']} (score: {item['score']:.2f})"
            for item in similar_items
        )

        prompt = f"""You are a memory deduplication assistant. Decide whether to create a new memory or skip.

New memory:
- Type: {memory_type}
- Summary: {summary}

Similar existing memories:
{similar_text}

Output your decision in JSON format:
{{
  "decision": "skip" or "create",
  "actions": [
    {{"id": "item_id", "action": "merge" or "delete", "reason": "explanation"}}
  ]
}}

Rules:
- If the new memory is semantically identical to an existing one, skip and mark for merge.
- If the new memory contradicts an existing one, create and mark the old one for delete.
- If the new memory is distinct, create it."""

        try:
            response = await self._llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self._model,
                max_tokens=300,
            )

            import json
            data = json.loads(response.content or "{}")

            decision_str = data.get("decision", "create").lower()
            decision = DedupDecision.CREATE if decision_str == "create" else DedupDecision.SKIP

            actions = []
            for action_data in data.get("actions", []):
                action_str = action_data.get("action", "merge").lower()
                action = MemoryAction.MERGE if action_str == "merge" else MemoryAction.DELETE
                actions.append(
                    ExistingAction(
                        item_id=action_data.get("id", ""),
                        summary=action_data.get("summary", ""),
                        action=action,
                        reason=action_data.get("reason", ""),
                    )
                )

            return decision, actions

        except Exception as exc:
            logger.exception("LLM deduplication decision failed: %s", exc)
            # 回退：如果相似度低则创建
            max_score = max(item["score"] for item in similar_items)
            if max_score < 0.7:
                return DedupDecision.CREATE, []
            return DedupDecision.SKIP, []

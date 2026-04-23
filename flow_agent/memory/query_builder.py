from dataclasses import dataclass

from flow_agent.memory.query_rewriter import QueryRewriteResult


@dataclass(slots=True)
class RetrievalPlan:
    query: str
    intent: str
    max_items: int
    filters: dict[str, str]


class RetrievalQueryBuilder:
    """Build retrieval query plan from rewritten query."""

    def build(self, rewrite: QueryRewriteResult, *, max_items: int = 6) -> RetrievalPlan:
        filters: dict[str, str] = {}
        if rewrite.intent in {"identity", "preference", "goal"}:
            filters["intent"] = rewrite.intent
        return RetrievalPlan(
            query=rewrite.rewritten_query,
            intent=rewrite.intent,
            max_items=max(0, max_items),
            filters=filters,
        )


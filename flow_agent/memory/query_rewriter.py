from dataclasses import dataclass
import re


@dataclass(slots=True)
class QueryRewriteResult:
    rewritten_query: str
    intent: str
    hints: list[str]


class QueryRewriter:
    """Rewrite user query for retrieval and infer implicit intent."""

    _token_re = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)

    def rewrite(self, query: str) -> QueryRewriteResult:
        text = (query or "").strip()
        if not text:
            return QueryRewriteResult(rewritten_query="", intent="empty", hints=[])
        hints: list[str] = []
        lowered = text.lower()
        if "叫什么" in text or "name" in lowered:
            hints.append("identity")
        if "喜欢" in text or "prefer" in lowered:
            hints.append("preference")
        if "计划" in text or "goal" in lowered:
            hints.append("goal")
        tokens = self._token_re.findall(text)
        rewritten = " ".join(tokens[:12])
        intent = hints[0] if hints else "general"
        return QueryRewriteResult(rewritten_query=rewritten, intent=intent, hints=hints)


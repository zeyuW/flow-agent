import re
from typing import Protocol

from flow_agent.memory.models import RetrievedMemory
from flow_agent.memory.query_builder import RetrievalQueryBuilder
from flow_agent.memory.query_rewriter import QueryRewriter
from flow_agent.memory.store import MessageStore

# 记忆检索器接口
class MemoryRetriever(Protocol):
    def retrieve(self, session_id: str, query: str, max_items: int) -> list[RetrievedMemory]:
        ...

# 关键词记忆检索器
class KeywordMemoryRetriever:
    def __init__(self, store: MessageStore) -> None:
        self.store = store
        self.rewriter = QueryRewriter()
        self.builder = RetrievalQueryBuilder()
        self.role_weight = {"user": 1.0, "assistant": 0.85}
        self.min_confidence = 0.18
    # 检索关键词相关的记忆
    def retrieve(self, session_id: str, query: str, max_items: int) -> list[RetrievedMemory]:
        if max_items <= 0:
            return []

        rewrite = self.rewriter.rewrite(query)
        plan = self.builder.build(rewrite, max_items=max_items)
        if not plan.query:
            plan = self.builder.build(query, max_items=max_items)
        query_tokens = _tokenize(plan.query) | _tokenize(query)
        if not query_tokens:
            return []

        memories: list[RetrievedMemory] = []
        all_messages = self.store.list_messages(session_id)
        total_messages = len(all_messages)
        for idx, msg in enumerate(all_messages):
            content = msg.get("content", "")
            role = msg.get("role", "")
            overlap = _keyword_overlap_score(query_tokens, _tokenize(content))
            recency = _recency_score(index=idx, total=total_messages)
            role_boost = self.role_weight.get(role, 0.7)
            score = (0.7 * overlap + 0.3 * recency) * role_boost
            if score <= 0:
                continue
            memories.append(RetrievedMemory(role=role, content=content, score=score))

        memories.sort(key=lambda m: m.score, reverse=True)
        top = _dedupe_by_content(memories)[: plan.max_items]
        if top and top[0].score < self.min_confidence:
            return []
        return top

# 正则表达：提取中文、英文、数字
_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)

# 分词：提取关键词
def _tokenize(text: str) -> set[str]:
    tokens: set[str] = set()
    for t in _TOKEN_RE.findall(text):
        t_lower = t.lower()
        tokens.add(t_lower)
        # 对中文做最小分词补充：按字符拆分，提升关键词召回鲁棒性
        if _is_cjk(t_lower) and len(t_lower) > 1:
            tokens.update(t_lower)
    return tokens

# 判断是否为中文字符
def _is_cjk(token: str) -> bool:
    for ch in token:
        code = ord(ch)
        if not (0x4E00 <= code <= 0x9FFF):
            return False
    return True

# 计算关键词重叠分数，越高越相关
def _keyword_overlap_score(query_tokens: set[str], doc_tokens: set[str]) -> float:
    if not doc_tokens:
        return 0.0
    overlap = query_tokens & doc_tokens
    return float(len(overlap)) / float(len(query_tokens))


def _recency_score(index: int, total: int) -> float:
    if total <= 1:
        return 1.0
    return float(index + 1) / float(total)


def _dedupe_by_content(memories: list[RetrievedMemory]) -> list[RetrievedMemory]:
    deduped: list[RetrievedMemory] = []
    seen: set[str] = set()
    for item in memories:
        key = " ".join(item.content.split()).strip().lower()[:120]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


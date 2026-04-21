import re
from typing import Protocol

from flow_agent.memory.models import RetrievedMemory
from flow_agent.memory.store import MessageStore

# 记忆检索器接口
class MemoryRetriever(Protocol):
    def retrieve(self, session_id: str, query: str, max_items: int) -> list[RetrievedMemory]:
        ...

# 关键词记忆检索器
class KeywordMemoryRetriever:
    def __init__(self, store: MessageStore) -> None:
        self.store = store
    # 检索关键词相关的记忆
    def retrieve(self, session_id: str, query: str, max_items: int) -> list[RetrievedMemory]:
        if max_items <= 0:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        memories: list[RetrievedMemory] = []
        for msg in self.store.list_messages(session_id):
            content = msg.get("content", "")
            role = msg.get("role", "")
            score = _keyword_overlap_score(query_tokens, _tokenize(content))
            if score <= 0:
                continue
            memories.append(RetrievedMemory(role=role, content=content, score=score))

        memories.sort(key=lambda m: m.score, reverse=True)
        return memories[:max_items]

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


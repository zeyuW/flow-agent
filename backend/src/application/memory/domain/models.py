"""记忆模块共享的领域模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


@dataclass(slots=True)
class MemoryItem:
    """一条记忆领域实体，包含可选的向量表示。"""

    id: str
    memory_type: str
    summary: str
    embedding: list[float] | None
    content_hash: str
    reinforcement: int = 1
    emotional_weight: int = 0
    status: str = "active"
    source_ref: str = ""
    happened_at: str = ""
    extra_json: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为可序列化的记忆字典。"""

        return {
            "id": self.id,
            "memory_type": self.memory_type,
            "summary": self.summary,
            "embedding": self.embedding,
            "content_hash": self.content_hash,
            "reinforcement": self.reinforcement,
            "emotional_weight": self.emotional_weight,
            "status": self.status,
            "source_ref": self.source_ref,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class RetrievalHit:
    """一次记忆检索命中及其排序分数。"""

    item: MemoryItem
    score: float
    vector_score: float = 0.0
    keyword_score: float = 0.0


@dataclass(slots=True)
class UserProfile:
    """从对话中提取的用户画像分类。"""

    identity: list[str] = field(default_factory=list)
    fact: list[str] = field(default_factory=list)
    preference: list[str] = field(default_factory=list)
    need: list[str] = field(default_factory=list)
    task: list[str] = field(default_factory=list)
    goal: list[str] = field(default_factory=list)
    constraint: list[str] = field(default_factory=list)
    milestone: list[str] = field(default_factory=list)
    routine: list[str] = field(default_factory=list)


class DedupDecision(str, Enum):
    """去重决策值：跳过、创建或未决定。"""

    SKIP = "skip"
    CREATE = "create"
    NONE = "none"


class MemoryAction(str, Enum):
    """相似记忆的处理动作。"""

    MERGE = "merge"
    DELETE = "delete"


@dataclass(slots=True)
class ExistingAction:
    """针对已有记忆的一项处理动作。"""

    item_id: str
    summary: str
    action: MemoryAction
    reason: str = ""


@dataclass(slots=True)
class DedupResult:
    """一次记忆去重决策的结果。"""

    decision: DedupDecision
    candidate_summary: str
    candidate_type: str
    similar_items: list[dict]
    actions: list[ExistingAction] = field(default_factory=list)
    reason: str = ""
    query_vector: list[float] | None = None

"""记忆失效检测：检测用户否定/纠错意图并 supersede 旧记忆。

实现 spec 4c-4e：
- 4c: 检测用户否定意图（从消息中提取"错了"、"不要这样"等模式）
- 4d: 检索相关旧记忆（根据失效主题召回可能需要失效的条目）
- 4e: 判断并执行 supersede（批量标记旧条目标记为失效）
"""

import logging
import math
from dataclasses import dataclass, field

from application.memory.infra.vector_store import MemoryItem, MemoryStore

logger = logging.getLogger(__name__)

# 否定/纠错触发词
NEGATION_PATTERNS = [
    "错了", "不对", "不要这样", "别再", "不要再说",
    "改一下", "纠正", "修正", "更正",
    "wrong", "incorrect", "don't", "stop",
    "forget", "forgot", "忘记", "忘了",
    "不是这样的", "之前说的不对",
]


@dataclass(slots=True)
class SupersedeDetection:
    """失效检测结果。"""

    has_negation: bool
    topic: str  # 被否定的主题
    matched_pattern: str
    related_ids: list[int] = field(default_factory=list)
    superseded_count: int = 0


class SupersedeDetector:
    """记忆失效检测器。

    当用户消息中包含否定/纠错意图时，自动检测并 supersede 相关旧记忆。
    """

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def detect_negation(self, user_message: str) -> list[SupersedeDetection]:
        """检测用户消息中的否定意图（spec 4c）。

        返回所有检测到的失效主题列表。
        """
        if not user_message.strip():
            return []

        detections: list[SupersedeDetection] = []
        lowered = user_message.lower()

        for pattern in NEGATION_PATTERNS:
            if pattern in lowered:
                # 提取被否定的主题：否定词周围的短语
                topic = self._extract_topic(user_message, pattern)
                detections.append(SupersedeDetection(
                    has_negation=True,
                    topic=topic,
                    matched_pattern=pattern,
                ))

        return detections

    def process_supersede(
        self,
        user_message: str,
    ) -> list[int]:
        """处理一条用户消息的 supersede 检测和执行（spec 4d-4e）。

        Args:
            user_message: 用户消息文本。

        Returns:
            被 supersede 的记忆 ID 列表。
        """
        detections = self.detect_negation(user_message)
        if not detections:
            return []

        all_superseded: set[int] = set()

        for det in detections:
            # spec 4d: 根据失效主题召回相关旧记忆
            related = self._find_related(det.topic)
            det.related_ids = [r.id for r in related]

            if related:
                # spec 4e: 批量标记失效
                ids = [r.id for r in related]
                self.store.mark_superseded_batch(ids)
                det.superseded_count = len(ids)
                all_superseded.update(ids)
                logger.info(
                    "superseded %d memories for topic '%s' (pattern: %s)",
                    len(ids),
                    det.topic,
                    det.matched_pattern,
                )

        return list(all_superseded)

    def _extract_topic(self, text: str, pattern: str) -> str:
        """从包含否定词的文本中提取被否定的主题。"""
        lowered = text.lower()
        idx = lowered.index(pattern)
        # 取否定词前后的文本（总共约 60 字符）作为主题
        start = max(0, idx - 15)
        end = min(len(text), idx + len(pattern) + 30)
        return text[start:end].strip()

    def _find_related(self, topic: str, top_k: int = 5) -> list[MemoryItem]:
        """根据失效主题检索相关的旧记忆（spec 4d）。

        使用简单的关键词重叠匹配（不需要 embedding API 调用）。
        """
        all_items = self.store.list_active()
        if not all_items:
            return []

        topic_tokens = set(topic.lower().split())
        if not topic_tokens:
            return []

        scored: list[tuple[MemoryItem, float]] = []
        for item in all_items:
            item_tokens = set(item.summary.lower().split())
            if not item_tokens:
                continue
            overlap = len(topic_tokens & item_tokens) / len(topic_tokens)
            if overlap > 0.3:  # 至少 30% 关键词重叠
                scored.append((item, overlap))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [item for item, _ in scored[:top_k]]

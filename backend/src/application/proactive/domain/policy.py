"""主动回复的策略值对象。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProactivePolicy:
    """单个会话的主动推送策略。"""

    enabled: bool = False
    idle_threshold_seconds: float = 0.0
    topics: tuple[str, ...] = ()

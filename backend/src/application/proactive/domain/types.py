"""主动回复领域中的来源、候选与调度类型。"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class SourceRecord:
    """从内部或外部来源获取的标准化内容。"""

    source: str
    title: str
    content: str
    dedup_key: str
    summary: str = ""
    priority_hint: float = 0.0
    fetched_at: datetime | None = None


@dataclass(slots=True)
class ProactiveCandidate:
    """可以由决策层评估的候选项。"""

    key: str
    content: str
    source: str = "unknown"
    priority: float = 0.0


@dataclass(slots=True)
class ProactiveGateDecision:
    """是否允许主动发送。"""

    allowed: bool
    reason: str


@dataclass(slots=True)
class ProactiveTickResult:
    """一次主动运行是否发送。"""

    sent: bool
    reason: str
    candidate_key: str | None = None


@dataclass(slots=True)
class SchedulerStatus:
    """主动调度器当前状态。"""

    running: bool
    is_executing: bool
    last_started_at: datetime | None
    last_finished_at: datetime | None

from dataclasses import dataclass
from datetime import datetime


'''源记录'''
@dataclass(slots=True)
class SourceRecord:
    '''标准化内容从内部或外部来源获取'''

    source: str
    title: str
    content: str
    dedup_key: str
    summary: str = ""
    priority_hint: float = 0.0
    fetched_at: datetime | None = None


'''主动候选项'''
@dataclass(slots=True)
class ProactiveCandidate:
    '''可以由决策层评估的候选项'''

    key: str
    content: str
    source: str = "unknown"
    priority: float = 0.0


'''主动决策'''
@dataclass(slots=True)
class ProactiveGateDecision:
    '''是否允许主动发送'''
    allowed: bool
    '''原因'''
    reason: str


'''主动运行时结果'''
@dataclass(slots=True)
class ProactiveTickResult:
    '''是否发送'''
    sent: bool
    '''原因'''
    reason: str
    '''候选键'''
    candidate_key: str | None = None


@dataclass(slots=True)
class SchedulerStatus:
    '''是否运行'''
    running: bool
    '''是否执行'''
    is_executing: bool
    '''上次开始时间'''
    last_started_at: datetime | None
    '''上次结束时间'''
    last_finished_at: datetime | None


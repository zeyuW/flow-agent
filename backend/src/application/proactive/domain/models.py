"""主动回复管道的领域数据模型。"""

import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(slots=True)
class AgentTick:
    """在主动阶段之间传递的单轮上下文。"""

    chat_id: str = ""
    base_score: float = 0.0
    gate_result: "GateResult | None" = None
    gateway_result: "GatewayResult | None" = None
    judge_result: "JudgeResult | None" = None
    resolve_result: "ResolveResult | None" = None
    deliver_result: "DeliverResult | None" = None
    drift_tick: Any | None = None
    phase_trace: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0

    @property
    def sent(self) -> bool:
        """本轮是否完成了真实出站投递。"""

        return bool(self.deliver_result and self.deliver_result.sent)


@dataclass(slots=True)
class GateResult:
    """准入阶段结果。"""

    passed: bool
    reason: str
    next_interval: float = 60.0


@dataclass(slots=True)
class DataItem:
    """主动数据源返回的标准化条目。"""

    source: str
    item_id: str
    title: str
    source_key: str = ""
    summary: str = ""
    content: str = ""
    ack_server: str = ""
    priority_hint: float = 0.0


@dataclass(slots=True)
class GatewayResult:
    """采集阶段的三个数据通道。"""

    alerts: list[DataItem] = field(default_factory=list)
    content: list[DataItem] = field(default_factory=list)
    context: list[DataItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def all_items(self) -> list[DataItem]:
        """按告警、内容、上下文顺序返回全部条目。"""

        return self.alerts + self.content + self.context


@dataclass(slots=True)
class JudgeResult:
    """内容评估阶段结果。"""

    decision: str
    message: str = ""
    cited_item_ids: list[str] = field(default_factory=list)
    discarded_ids: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


@dataclass(slots=True)
class ResolveResult:
    """发送前解析和去重结果。"""

    decision: str
    message: str = ""
    cited_item_ids: list[str] = field(default_factory=list)
    delivery_key: str = ""
    side_effects: list[Callable] = field(default_factory=list)


@dataclass(slots=True)
class DeliverResult:
    """最终出站投递结果。"""

    sent: bool
    message: str = ""
    chat_id: str = ""
    error: str | None = None

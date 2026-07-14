"""主动管道的数据模型。"""

from dataclasses import dataclass, field
from typing import Any, Callable


# ── Tick 上下文 ──

@dataclass(slots=True)
class AgentTick:
    """在所有管道阶段中传递的上下文。"""
    chat_id: str = ""
    base_score: float = 0.0
    gate_result: "GateResult | None" = None
    gateway_result: "GatewayResult | None" = None
    judge_result: "JudgeResult | None" = None
    resolve_result: "ResolveResult | None" = None
    deliver_result: "DeliverResult | None" = None
    drift_tick = None  # DriftTick | None
    trace: str = ""


# ── Gate ──

@dataclass(slots=True)
class GateResult:
    passed: bool
    reason: str
    next_interval: float = 60.0


# ── Fetch / DataGateway ──

@dataclass(slots=True)
class DataItem:
    source: str
    item_id: str
    title: str
    summary: str = ""
    content: str = ""
    ack_server: str = ""
    priority_hint: float = 0.0


@dataclass(slots=True)
class GatewayResult:
    alerts: list[DataItem] = field(default_factory=list)
    content: list[DataItem] = field(default_factory=list)
    context: list[DataItem] = field(default_factory=list)

    @property
    def all_items(self) -> list[DataItem]:
        return self.alerts + self.content + self.context


# ── Judge ──

@dataclass(slots=True)
class JudgeResult:
    decision: str  # reply | skip
    message: str = ""
    cited_item_ids: list[str] = field(default_factory=list)
    discarded_ids: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


# ── Resolve ──

@dataclass(slots=True)
class ResolveResult:
    decision: str  # send | skip
    message: str = ""
    cited_item_ids: list[str] = field(default_factory=list)
    delivery_key: str = ""
    side_effects: list[Callable] = field(default_factory=list)


# ── Deliver ──

@dataclass(slots=True)
class DeliverResult:
    sent: bool
    message: str = ""
    chat_id: str = ""
    error: str | None = None

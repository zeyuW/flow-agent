"""Gate: 主动 tick 前的准入检查。"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from flow_agent.proactive.models import GateResult


@dataclass(slots=True)
class ProactiveStateStore:
    """Tracks last sent time, delivery keys, and drift timestamp for gate + dedup."""
    _last_sent: float = 0.0
    _delivery_keys: dict[str, float] = field(default_factory=dict)
    _daily_count: int = 0
    _day_start: float = 0.0
    _drift_last_at: float = 0.0

    def get_last_sent_at(self) -> float:
        return self._last_sent

    def mark_sent(self, delivery_key: str = "") -> None:
        now = time.time()
        self._last_sent = now
        if delivery_key:
            self._delivery_keys[delivery_key] = now
        day = int(now // 86400)
        if int(self._day_start // 86400) != day:
            self._daily_count = 0
            self._day_start = now
        self._daily_count += 1

    def was_delivered(self, delivery_key: str, window: float = 3600) -> bool:
        ts = self._delivery_keys.get(delivery_key, 0)
        return (time.time() - ts) < window

    @property
    def daily_count(self) -> int:
        day = int(time.time() // 86400)
        if int(self._day_start // 86400) != day:
            return 0
        return self._daily_count

    def mark_drift_run(self) -> None:
        self._drift_last_at = time.time()

    def get_drift_last_at(self) -> float:
        return self._drift_last_at


@dataclass(slots=True)
class AnyActionGate:
    """简化的 Gate 机制：仅保留每日最大次数限制，调度完全由霍克斯过程控制。"""
    max_per_day: int = 5

    def should_act(self, store: ProactiveStateStore, base_score: float) -> bool:
        # 只检查每日最大次数限制
        if store.daily_count >= self.max_per_day:
            return False
        return True


def check_gate(
    *,
    chat_id: str = "",
    is_busy: bool = False,
    state_store: ProactiveStateStore | None = None,
    any_action: AnyActionGate | None = None,
    cooldown: float = 120.0,
    base_score: float = 0.0,
) -> GateResult:
    """按优先级顺序运行所有 gate 检查。

    1. 目标检查
    2. 忙碌检查
    3. 冷却时间
    4. AnyAction 配额
    """
    if not chat_id:
        return GateResult(passed=False, reason="no_target")

    if is_busy:
        return GateResult(passed=False, reason="passive_busy")

    if state_store:
        last = state_store.get_last_sent_at()
        if last > 0 and (time.time() - last) < cooldown:
            return GateResult(passed=False, reason="cooldown")

    if any_action and state_store:
        if not any_action.should_act(state_store, base_score):
            return GateResult(passed=False, reason="any_action_blocked")

    # Adaptive interval: higher score → shorter interval
    next_interval = max(30.0, 300.0 - base_score * 200.0)
    return GateResult(passed=True, reason="ok", next_interval=next_interval)

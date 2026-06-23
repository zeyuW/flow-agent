"""Gate: admission checks before proactive tick (spec 2)."""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from flow_agent.proactive.models import GateResult


@dataclass(slots=True)
class ProactiveStateStore:
    """Tracks last sent time and delivery keys for gate + dedup."""
    _last_sent: float = 0.0
    _delivery_keys: dict[str, float] = field(default_factory=dict)
    _daily_count: int = 0
    _day_start: float = 0.0

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


@dataclass(slots=True)
class AnyActionGate:
    """Quota-based admission: daily limit, min interval, probability (spec 2e)."""
    max_per_day: int = 5
    min_interval: float = 300.0
    prob_threshold: float = 0.3

    def should_act(self, store: ProactiveStateStore, base_score: float) -> bool:
        if store.daily_count >= self.max_per_day:
            return False
        last = store.get_last_sent_at()
        if last > 0 and (time.time() - last) < self.min_interval:
            return False
        if base_score < self.prob_threshold:
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
    """Run all gate checks in priority order (spec 2a-2e).

    1. Target check (spec 2b)
    2. Busy check (spec 2c)
    3. Cooldown (spec 2d)
    4. AnyAction quota (spec 2e)
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

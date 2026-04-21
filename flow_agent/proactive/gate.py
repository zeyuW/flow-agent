from datetime import datetime, timedelta, timezone

from flow_agent.proactive.models import ProactiveGateDecision
from flow_agent.proactive.store import ProactiveSentStore


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SimplePreGate:
    def __init__(self, sent_store: ProactiveSentStore, cooldown_seconds: int) -> None:
        self.sent_store = sent_store
        self.cooldown_seconds = cooldown_seconds

    def check(self) -> ProactiveGateDecision:
        last_sent_at = self.sent_store.get_last_sent_at()
        if last_sent_at is None:
            return ProactiveGateDecision(allowed=True, reason="ok")

        now = _utc_now()
        if now - last_sent_at < timedelta(seconds=self.cooldown_seconds):
            return ProactiveGateDecision(allowed=False, reason="cooldown")
        return ProactiveGateDecision(allowed=True, reason="ok")

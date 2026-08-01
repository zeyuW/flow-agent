from dataclasses import dataclass


@dataclass(slots=True)
class DelegationDecision:
    action: str  # handle_locally | spawn_subagent | background_job | reject
    reason: str


@dataclass(slots=True)
class DelegationPolicy:
    """Rule-based delegation policy."""

    max_local_chars: int = 500
    reject_keywords: tuple[str, ...] = ("危险", "删库", "rm -rf")

    def decide(self, *, user_input: str, tool_step_budget: int) -> DelegationDecision:
        text = user_input.strip()
        if any(k in text for k in self.reject_keywords):
            return DelegationDecision(action="reject", reason="unsafe_request")
        if "多步" in text or "委派" in text or "subagent" in text.lower():
            return DelegationDecision(action="spawn_subagent", reason="multi_step")
        if len(text) > self.max_local_chars or "长耗时" in text or "后台" in text:
            return DelegationDecision(action="background_job", reason="long_running")
        if tool_step_budget <= 1 and ("复杂" in text or "批量" in text):
            return DelegationDecision(action="spawn_subagent", reason="complexity_exceeds_local")
        return DelegationDecision(action="handle_locally", reason="default")


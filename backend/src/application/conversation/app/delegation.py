"""对话请求的本地处理、委托和拒绝规则。"""

from dataclasses import dataclass


@dataclass(slots=True)
class DelegationDecision:
    """一次请求的处理决策。"""

    action: str
    reason: str


@dataclass(slots=True)
class DelegationPolicy:
    """根据请求特征选择处理路径的应用策略。"""

    max_local_chars: int = 500
    reject_keywords: tuple[str, ...] = ("危险", "删库", "rm -rf")

    def decide(self, *, user_input: str, tool_step_budget: int) -> DelegationDecision:
        """返回本地处理、子代理、后台任务或拒绝决策。"""

        text = user_input.strip()
        if any(keyword in text for keyword in self.reject_keywords):
            return DelegationDecision(action="reject", reason="unsafe_request")
        if "多步" in text or "委派" in text or "subagent" in text.lower():
            return DelegationDecision(action="spawn_subagent", reason="multi_step")
        if len(text) > self.max_local_chars or "长耗时" in text or "后台" in text:
            return DelegationDecision(action="background_job", reason="long_running")
        if tool_step_budget <= 1 and ("复杂" in text or "批量" in text):
            return DelegationDecision(
                action="spawn_subagent", reason="complexity_exceeds_local"
            )
        return DelegationDecision(action="handle_locally", reason="default")

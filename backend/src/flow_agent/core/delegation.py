"""旧核心路径的委托策略转发层。"""

from modules.conversation.application.delegation import (
    DelegationDecision,
    DelegationPolicy,
)

__all__ = ["DelegationDecision", "DelegationPolicy"]

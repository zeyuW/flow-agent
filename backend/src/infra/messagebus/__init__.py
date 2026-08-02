"""共享消息基础设施。"""

from infra.messagebus.queues import InboundQueue, OutboundQueue

__all__ = ["InboundQueue", "OutboundQueue"]

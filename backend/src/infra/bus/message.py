"""不依赖业务模块的双向消息总线外观。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from infra.bus.queues import InboundQueue, OutboundCallback, OutboundQueue


@dataclass
class MessageBus:
    """封装入站和出站队列，提供业务可复用的消息传输接口。"""

    inbound: InboundQueue = field(default_factory=InboundQueue)
    outbound: OutboundQueue = field(default_factory=OutboundQueue)

    def publish_inbound(self, message: Any) -> None:
        """发布一条入站消息。"""

        self.inbound.publish(message)

    def consume_inbound(self) -> Any | None:
        """非阻塞消费一条入站消息。"""

        return self.inbound.consume_one()

    async def consume_inbound_async(self, poll_interval_ms: int = 100) -> Any | None:
        """异步等待并消费一条入站消息。"""

        return await self.inbound.consume_one_async(poll_interval_ms)

    def subscribe_outbound(self, channel: str, callback: OutboundCallback) -> None:
        """注册指定渠道的出站回调。"""

        self.outbound.subscribe(channel, callback)

    def unsubscribe_outbound(self, channel: str, callback: OutboundCallback) -> None:
        """取消指定渠道的出站回调。"""

        self.outbound.unsubscribe(channel, callback)

    def publish_outbound(self, message: Any) -> None:
        """将出站消息放入队列，不立即触发回调。"""

        self.outbound.publish(message)

    def dispatch_outbound(self, message: Any) -> None:
        """将出站消息放入队列并同步分发给渠道回调。"""

        self.outbound.dispatch(message)

from typing import Protocol

from infra.bus.types import ChannelDeliveryResult, OutboundMessage
from application.conversation.domain.channel_message import InboundMessage


class OutboundSubscriber(Protocol):
    """出站消息订阅者协议：渠道适配器实现此接口来接收待发送的回复。"""

    def on_outbound(self, message: OutboundMessage) -> None:
        ...

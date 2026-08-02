"""将投递总线转换为对话应用的入站适配器。"""

from modules.delivery.infra.delivery_bus import DeliveryBus
from modules.conversation.domain.messages import IncomingMessage


class InboundSource:
    """从投递总线读取消息并转换为对话领域协议。"""

    def __init__(self, bus: DeliveryBus) -> None:
        self._bus = bus

    async def receive(self, poll_interval_ms: int) -> IncomingMessage:
        """等待一条入站消息，并转换为对话领域字段。"""

        inbound = await self._bus.consume_inbound_async(poll_interval_ms)
        if inbound is None:
            raise RuntimeError("消息总线在等待期间未返回入站消息")
        return IncomingMessage(
            channel=inbound.channel,
            conversation_id=inbound.session_id,
            text=inbound.text,
            sender_id=inbound.sender,
            media=tuple(inbound.media),
            received_at=inbound.received_at,
            metadata=dict(inbound.metadata),
        )

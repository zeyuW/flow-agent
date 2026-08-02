"""将既有消息总线作为对话应用的入站适配器。"""

from modules.delivery.infra.message_bus import MessageBus
from modules.conversation.domain.messages import IncomingMessage


class LegacyMessageBusSource:
    """从既有总线读取消息并转换为对话领域协议。"""

    def __init__(self, bus: MessageBus) -> None:
        self._bus = bus

    async def receive(self, poll_interval_ms: int) -> IncomingMessage:
        """等待一条旧总线消息，再消除旧字段命名。"""

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

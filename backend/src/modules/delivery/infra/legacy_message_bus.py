"""将既有消息总线接入投递模块端口。"""

from modules.delivery.infra.message_bus import MessageBus, OutboundDispatch
from modules.delivery.application.ports import (
    DeliveryReceipt,
    DeliveryRequest,
    DeliverySubmission,
)


class LegacyMessageBusDeliveryPort:
    """使用既有 Outbox 与渠道分发器完成可靠投递。"""

    def __init__(self, bus: MessageBus) -> None:
        self._bus = bus

    def submit(self, request: DeliveryRequest) -> DeliverySubmission:
        """将请求写入既有 Outbox，返回稳定的投递关联标识。"""

        handle = self._bus.outbound_port.send(self._to_dispatch(request))
        return DeliverySubmission(delivery_id=handle.delivery_id)

    async def send_and_wait(
        self,
        request: DeliveryRequest,
        *,
        timeout: float,
    ) -> DeliveryReceipt:
        """委托旧总线发送，并将其回执转换为投递领域回执。"""

        receipt = await self._bus.outbound_port.send_and_wait(
            self._to_dispatch(request), timeout=timeout
        )
        return DeliveryReceipt(
            delivery_id=receipt.delivery_id,
            delivered=receipt.delivered,
            attempts=receipt.attempts,
            error=receipt.error,
            uncertain=receipt.uncertain,
            retryable=receipt.retryable,
        )

    @staticmethod
    def _to_dispatch(request: DeliveryRequest) -> OutboundDispatch:
        return OutboundDispatch(
            channel=request.channel,
            session_id=request.conversation_id,
            chat_id=request.recipient_id,
            text=request.text,
            delivery_id=request.delivery_id,
            metadata=dict(request.metadata),
        )

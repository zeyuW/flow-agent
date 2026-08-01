"""投递模块向其他业务模块暴露的稳定端口。"""

from dataclasses import dataclass, field
from typing import Mapping, Protocol


@dataclass(frozen=True, slots=True)
class DeliveryRequest:
    """一条等待发送到外部渠道的业务投递请求。"""

    channel: str
    conversation_id: str
    text: str
    recipient_id: str = ""
    delivery_id: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    """投递执行后的稳定结果。"""

    delivery_id: str
    delivered: bool
    attempts: int = 0
    error: str = ""
    uncertain: bool = False
    retryable: bool = True

    @classmethod
    def delivered_for(
        cls, request: DeliveryRequest, *, attempts: int
    ) -> "DeliveryReceipt":
        """构造确认送达的回执，确保关联同一个投递标识。"""

        return cls(
            delivery_id=request.delivery_id,
            delivered=True,
            attempts=attempts,
        )


@dataclass(frozen=True, slots=True)
class DeliverySubmission:
    """投递请求已被可靠队列接收后的关联标识。"""

    delivery_id: str


class DeliveryPort(Protocol):
    """供对话等业务用例提交出站消息的抽象端口。"""

    def submit(self, request: DeliveryRequest) -> DeliverySubmission:
        """可靠接收一条请求，后续结果由回执或等待接口提供。"""

        ...

    async def send_and_wait(
        self,
        request: DeliveryRequest,
        *,
        timeout: float,
    ) -> DeliveryReceipt:
        """提交请求并等待渠道返回可确认的投递结果。"""

        ...

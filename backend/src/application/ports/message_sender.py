"""业务层向外部渠道发送消息的端口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class SendMessage:
    """一条等待可靠发送到外部渠道的消息。"""

    channel: str
    recipient_id: str
    text: str
    conversation_id: str = ""
    message_id: str = ""
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SendResult:
    """消息进入可靠传输流程后的结果。"""

    message_id: str
    accepted: bool
    attempts: int = 0
    error: str = ""
    uncertain: bool = False


@runtime_checkable
class MessageSender(Protocol):
    """只暴露消息发送能力的业务端口。"""

    def send(self, message: SendMessage) -> SendResult:
        """将消息交给可靠消息传输设施。"""

        ...

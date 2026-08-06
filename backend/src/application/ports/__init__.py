"""业务模块共享端口。"""

from application.ports.message_consumer import MessageConsumer, ReceivedMessage
from application.ports.message_sender import MessageSender, SendMessage, SendResult

__all__ = [
    "MessageConsumer",
    "MessageSender",
    "ReceivedMessage",
    "SendMessage",
    "SendResult",
]

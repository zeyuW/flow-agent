"""被动语义的 Agent Loop 适配器。

AgentLoop 只负责通用并发和生命周期；本模块负责把消息总线中的
``ReceivedMessage`` 转换成 passive 业务使用的 ``IncomingMessage``。
"""

from __future__ import annotations

from application.agent.app.loop import AgentLoop
from application.passive.domain.messages import IncomingMessage
from infra.bus.types import MessageConsumer, ReceivedMessage


def to_incoming_message(message: ReceivedMessage) -> IncomingMessage:
    """将共享消息总线消息转换为被动业务消息。"""

    return IncomingMessage(
        channel=message.channel,
        conversation_id=message.conversation_id,
        text=message.text,
        sender_id=message.sender_id,
        media=message.media,
        metadata=dict(message.metadata),
        chat_id=message.chat_id,
    )


class PassiveLoop(AgentLoop):
    """被动消息入口，复用 AgentLoop 的并发和生命周期能力。"""

    def __init__(
        self,
        consumer: MessageConsumer,
        processor,
        *,
        event_bus=None,
        poll_interval_ms: int = 100,
    ) -> None:
        super().__init__(
            consumer=consumer,
            processor=processor,
            event_bus=event_bus,
            message_mapper=to_incoming_message,
            poll_interval_ms=poll_interval_ms,
        )

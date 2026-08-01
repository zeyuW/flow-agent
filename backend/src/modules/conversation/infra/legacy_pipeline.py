"""在迁移期把新的对话协议接入既有回合执行器。"""

from typing import Protocol

from flow_agent.channels.models import InboundMessage
from modules.conversation.domain.messages import IncomingMessage


class _LegacyPassiveTurnPipeline(Protocol):
    """旧回合管道在迁移期保留的最小能力。"""

    async def process_async(self, inbound: InboundMessage) -> None:
        """异步处理一条旧协议入站消息。"""


class LegacyPipelineProcessor:
    """将新协议转换为旧管道可处理的输入。"""

    def __init__(self, pipeline: _LegacyPassiveTurnPipeline) -> None:
        self._pipeline = pipeline

    async def process(self, message: IncomingMessage) -> None:
        """保持全部输入信息后调用已有回合引擎。"""

        await self._pipeline.process_async(
            InboundMessage(
                channel=message.channel,
                session_id=message.conversation_id,
                text=message.text,
                sender=message.sender_id,
                media=list(message.media),
                received_at=message.received_at,
                metadata=dict(message.metadata),
            )
        )

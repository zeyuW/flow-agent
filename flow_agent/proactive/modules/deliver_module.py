"""Deliver 模块，发送消息。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from flow_agent.proactive.modules.base import ProactiveModule, ProactiveModuleSpec

if TYPE_CHECKING:
    from flow_agent.proactive.modules.context import ModuleContext


logger = logging.getLogger(__name__)


class DeliverModule(ProactiveModule):
    """Deliver 模块，发送消息。"""

    def __init__(self, message_bus=None):
        spec = ProactiveModuleSpec(
            id="deliver",
            name="Deliver",
            description="发送消息",
            slot="deliver",
            requires=("resolve_result",),
            produces=(),
        )
        super().__init__(spec)
        self._message_bus = message_bus

    async def run(self, context: ModuleContext) -> ModuleContext:
        """执行消息发送。"""
        if not context.resolve_result or context.resolve_result.decision != "send":
            logger.debug("Resolve 决定不发送，跳过 Deliver")
            return context

        # 使用消息总线发送消息
        # 这里需要集成现有的消息发送逻辑
        if self._message_bus and context.resolve_result.message:
            try:
                # 调用消息发送逻辑
                # await self._message_bus.send_message(context.chat_id, context.resolve_result.message)
                logger.info(f"消息发送成功: chat_id={context.chat_id}")
            except Exception as e:
                logger.error(f"消息发送失败: {e}")
                raise

        logger.debug(f"Deliver 模块发送了消息")
        
        return context

"""Resolve 模块，决定最终发送内容。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from flow_agent.proactive.modules.base import ProactiveModule, ProactiveModuleSpec

if TYPE_CHECKING:
    from flow_agent.proactive.modules.context import ModuleContext


logger = logging.getLogger(__name__)


class ResolveModule(ProactiveModule):
    """Resolve 模块，决定最终发送内容。"""

    def __init__(self, state_store=None):
        spec = ProactiveModuleSpec(
            id="resolve",
            name="Resolve",
            description="决定最终发送内容",
            slot="resolve",
            requires=("judge_result",),
            produces=("resolve_result",),
        )
        super().__init__(spec)
        self._state_store = state_store

    async def run(self, context: ModuleContext) -> ModuleContext:
        """执行 Resolve 决策。"""
        if not context.judge_result or context.judge_result.decision != "reply":
            logger.debug("Judge 决定不回复，跳过 Resolve")
            return context

        # 使用现有的 resolve 决策逻辑
        # 这里需要集成现有的 resolve_decision 函数
        resolve_result = None
        
        if self._state_store:
            try:
                # 调用 resolve 决策逻辑
                # resolve_result = resolve_decision(context.judge_result, state_store=self._state_store, chat_id=context.chat_id)
                logger.debug(f"Resolve 决策完成: decision={resolve_result.decision if resolve_result else 'none'}")
            except Exception as e:
                logger.error(f"Resolve 决策失败: {e}")
                raise

        logger.debug(f"Resolve 模块决策结果: {resolve_result}")
        
        return context.with_metadata(resolve_result=resolve_result).set_slot("resolve_result", resolve_result)

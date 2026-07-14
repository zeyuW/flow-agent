"""Judge 模块，判断是否需要发送消息。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from flow_agent.proactive.modules.base import ProactiveModule, ProactiveModuleSpec

if TYPE_CHECKING:
    from flow_agent.proactive.modules.context import ModuleContext


logger = logging.getLogger(__name__)


class JudgeModule(ProactiveModule):
    """Judge 模块，判断是否需要发送消息。"""

    def __init__(self, judge_loop=None):
        spec = ProactiveModuleSpec(
            id="judge",
            name="Judge",
            description="判断是否需要发送消息",
            slot="judge",
            requires=("raw_data",),
            produces=("judge_result",),
        )
        super().__init__(spec)
        self._judge_loop = judge_loop

    async def run(self, context: ModuleContext) -> ModuleContext:
        """执行 Judge 判断。"""
        if not context.raw_data:
            logger.debug("没有数据，跳过 Judge")
            return context

        # 使用 JudgeLoop 进行判断
        # 这里需要集成现有的 JudgeLoop
        judge_result = None
        
        if self._judge_loop:
            try:
                # 调用 JudgeLoop 进行判断
                # judge_result = await self._judge_loop.evaluate(context.raw_data, context.chat_id)
                logger.debug(f"Judge 判断完成: decision={judge_result.decision if judge_result else 'none'}")
            except Exception as e:
                logger.error(f"Judge 判断失败: {e}")
                raise

        logger.debug(f"Judge 模块判断结果: {judge_result}")
        
        return context.with_metadata(judge_result=judge_result).set_slot("judge_result", judge_result)

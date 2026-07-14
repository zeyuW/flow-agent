"""Fetch 模块，获取数据源。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from flow_agent.proactive.modules.base import ProactiveModule, ProactiveModuleSpec

if TYPE_CHECKING:
    from flow_agent.proactive.modules.context import ModuleContext


logger = logging.getLogger(__name__)


class FetchModule(ProactiveModule):
    """Fetch 模块，获取数据源。"""

    def __init__(self, data_gateway=None):
        spec = ProactiveModuleSpec(
            id="fetch",
            name="Fetch",
            description="获取数据源",
            slot="fetch",
            requires=("gate_result",),
            produces=("raw_data",),
        )
        super().__init__(spec)
        self._data_gateway = data_gateway

    async def run(self, context: ModuleContext) -> ModuleContext:
        """执行数据获取。"""
        if not context.gate_passed:
            logger.debug("Gate 未通过，跳过数据获取")
            return context

        # 使用数据网关获取数据
        # 这里需要集成现有的 DataGateway
        raw_data = []
        
        if self._data_gateway:
            try:
                # 调用数据网关获取数据
                # raw_data = await self._data_gateway.fetch(context.chat_id)
                logger.debug(f"数据获取成功: {len(raw_data)} 条")
            except Exception as e:
                logger.error(f"数据获取失败: {e}")
                raise

        logger.debug(f"Fetch 模块获取了 {len(raw_data)} 条数据")
        
        return context.with_metadata(raw_data=raw_data).set_slot("raw_data", raw_data)

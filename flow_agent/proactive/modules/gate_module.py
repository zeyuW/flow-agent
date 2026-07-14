"""Gate 模块，控制是否执行主动回复。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from flow_agent.proactive.modules.base import ProactiveModule, ProactiveModuleSpec

if TYPE_CHECKING:
    from flow_agent.proactive.modules.context import ModuleContext


logger = logging.getLogger(__name__)


class GateModule(ProactiveModule):
    """Gate 模块，控制是否执行主动回复。"""

    def __init__(self, max_per_day: int = 5):
        spec = ProactiveModuleSpec(
            id="gate",
            name="Gate",
            description="控制是否执行主动回复",
            slot="gate",
            produces=("gate_result",),
        )
        super().__init__(spec)
        self.max_per_day = max_per_day

    async def run(self, context: ModuleContext) -> ModuleContext:
        """执行 Gate 检查。"""
        # 简化的 Gate 逻辑：只检查每日最大次数限制
        # 这里需要从状态存储中获取每日计数
        # 暂时总是通过，实际应该检查状态存储
        
        gate_passed = True
        gate_reason = "ok"
        
        logger.debug(f"Gate 检查通过: passed={gate_passed}, reason={gate_reason}")
        
        return context.with_metadata(
            gate_passed=gate_passed,
            gate_reason=gate_reason,
        ).set_slot("gate_result", {"passed": gate_passed, "reason": gate_reason})

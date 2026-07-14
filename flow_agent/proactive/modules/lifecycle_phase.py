"""生命周期阶段定义，支持被动和主动回复链路管理。"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flow_agent.proactive.modules.base import ProactiveModule


class LifecyclePhase(Enum):
    """生命周期阶段。"""
    # 被动回复阶段
    BEFORE_TURN = "before_turn"          # 回复前处理
    BEFORE_REASONING = "before_reasoning"  # 推理前处理
    PROMPT_RENDER = "prompt_render"      # 提示词渲染
    BEFORE_STEP = "before_step"          # 步骤前处理
    AFTER_STEP = "after_step"            # 步骤后处理
    AFTER_REASONING = "after_reasoning"  # 推理后处理
    AFTER_TURN = "after_turn"            # 回复后处理
    
    # 主动回复阶段
    PROACTIVE_GATE = "proactive_gate"    # 主动回复门控
    PROACTIVE_FETCH = "proactive_fetch"  # 主动回复数据获取
    PROACTIVE_JUDGE = "proactive_judge"  # 主动回复判断
    PROACTIVE_RESOLVE = "proactive_resolve"  # 主动回复决策
    PROACTIVE_DELIVER = "proactive_deliver"  # 主动回复发送


class PhaseModule:
    """阶段模块包装器。"""
    
    def __init__(self, module: ProactiveModule, phase: LifecyclePhase, priority: int = 0):
        self.module = module
        self.phase = phase
        self.priority = priority
    
    @property
    def module_id(self) -> str:
        return self.module.spec.id
    
    @property
    def slot(self) -> str:
        return self.module.slot
    
    @property
    def requires(self) -> tuple[str, ...]:
        return self.module.requires
    
    @property
    def produces(self) -> tuple[str, ...]:
        return self.module.produces


class PhaseManager:
    """阶段管理器，统一管理被动和主动回复模块。"""
    
    def __init__(self):
        self._phase_modules: dict[LifecyclePhase, list[PhaseModule]] = {}
        for phase in LifecyclePhase:
            self._phase_modules[phase] = []
    
    def register_module(self, module: ProactiveModule, phase: LifecyclePhase, priority: int = 0) -> None:
        """注册模块到指定阶段。"""
        phase_module = PhaseModule(module, phase, priority)
        self._phase_modules[phase].append(phase_module)
        # 按优先级排序
        self._phase_modules[phase].sort(key=lambda pm: -pm.priority)
    
    def get_modules_by_phase(self, phase: LifecyclePhase) -> list[ProactiveModule]:
        """获取指定阶段的所有模块。"""
        return [pm.module for pm in self._phase_modules[phase]]
    
    def get_all_modules(self) -> dict[LifecyclePhase, list[ProactiveModule]]:
        """获取所有阶段的模块。"""
        return {phase: self.get_modules_by_phase(phase) for phase in LifecyclePhase}
    
    def execute_phase(self, phase: LifecyclePhase, context) -> None:
        """执行指定阶段的所有模块。"""
        modules = self.get_modules_by_phase(phase)
        for module in modules:
            # 执行模块逻辑
            pass
    
    def execute_passive_pipeline(self, context) -> None:
        """执行被动回复管道。"""
        phases = [
            LifecyclePhase.BEFORE_TURN,
            LifecyclePhase.BEFORE_REASONING,
            LifecyclePhase.PROMPT_RENDER,
            LifecyclePhase.BEFORE_STEP,
            LifecyclePhase.AFTER_STEP,
            LifecyclePhase.AFTER_REASONING,
            LifecyclePhase.AFTER_TURN,
        ]
        for phase in phases:
            self.execute_phase(phase, context)
    
    def execute_proactive_pipeline(self, context) -> None:
        """执行主动回复管道。"""
        phases = [
            LifecyclePhase.PROACTIVE_GATE,
            LifecyclePhase.PROACTIVE_FETCH,
            LifecyclePhase.PROACTIVE_JUDGE,
            LifecyclePhase.PROACTIVE_RESOLVE,
            LifecyclePhase.PROACTIVE_DELIVER,
        ]
        for phase in phases:
            self.execute_phase(phase, context)

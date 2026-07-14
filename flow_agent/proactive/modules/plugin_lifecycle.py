"""插件生命周期管理，支持插件注册到生命周期阶段。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from flow_agent.proactive.modules.lifecycle_phase import LifecyclePhase

if TYPE_CHECKING:
    from flow_agent.proactive.modules.base import ProactiveModule


class PluginLifecycle(ABC):
    """插件生命周期基类。"""
    
    @abstractmethod
    def get_modules(self) -> list[tuple[ProactiveModule, LifecyclePhase, int]]:
        """获取插件提供的所有模块及其生命周期阶段和优先级。
        
        返回格式: [(module, phase, priority), ...]
        """
        pass
    
    def get_before_turn_modules(self) -> list[tuple[ProactiveModule, int]]:
        """获取 BEFORE_TURN 阶段的模块。"""
        return [(module, priority) for module, phase, priority in self.get_modules() 
                if phase == LifecyclePhase.BEFORE_TURN]
    
    def get_before_reasoning_modules(self) -> list[tuple[ProactiveModule, int]]:
        """获取 BEFORE_REASONING 阶段的模块。"""
        return [(module, priority) for module, phase, priority in self.get_modules() 
                if phase == LifecyclePhase.BEFORE_REASONING]
    
    def get_prompt_render_modules(self) -> list[tuple[ProactiveModule, int]]:
        """获取 PROMPT_RENDER 阶段的模块。"""
        return [(module, priority) for module, phase, priority in self.get_modules() 
                if phase == LifecyclePhase.PROMPT_RENDER]
    
    def get_before_step_modules(self) -> list[tuple[ProactiveModule, int]]:
        """获取 BEFORE_STEP 阶段的模块。"""
        return [(module, priority) for module, phase, priority in self.get_modules() 
                if phase == LifecyclePhase.BEFORE_STEP]
    
    def get_after_step_modules(self) -> list[tuple[ProactiveModule, int]]:
        """获取 AFTER_STEP 阶段的模块。"""
        return [(module, priority) for module, phase, priority in self.get_modules() 
                if phase == LifecyclePhase.AFTER_STEP]
    
    def get_after_reasoning_modules(self) -> list[tuple[ProactiveModule, int]]:
        """获取 AFTER_REASONING 阶段的模块。"""
        return [(module, priority) for module, phase, priority in self.get_modules() 
                if phase == LifecyclePhase.AFTER_REASONING]
    
    def get_after_turn_modules(self) -> list[tuple[ProactiveModule, int]]:
        """获取 AFTER_TURN 阶段的模块。"""
        return [(module, priority) for module, phase, priority in self.get_modules() 
                if phase == LifecyclePhase.AFTER_TURN]
    
    def get_proactive_modules(self) -> list[tuple[ProactiveModule, LifecyclePhase, int]]:
        """获取主动回复阶段的模块。"""
        return [(module, phase, priority) for module, phase, priority in self.get_modules() 
                if phase in [
                    LifecyclePhase.PROACTIVE_GATE,
                    LifecyclePhase.PROACTIVE_FETCH,
                    LifecyclePhase.PROACTIVE_JUDGE,
                    LifecyclePhase.PROACTIVE_RESOLVE,
                    LifecyclePhase.PROACTIVE_DELIVER,
                ]]


class ProactivePluginLifecycle(PluginLifecycle):
    """主动回复插件生命周期。"""
    
    def __init__(self, gate_module=None, fetch_module=None, judge_module=None, 
                 resolve_module=None, deliver_module=None):
        self._gate_module = gate_module
        self._fetch_module = fetch_module
        self._judge_module = judge_module
        self._resolve_module = resolve_module
        self._deliver_module = deliver_module
    
    def get_modules(self) -> list[tuple[ProactiveModule, LifecyclePhase, int]]:
        """获取主动回复模块。"""
        modules = []
        if self._gate_module:
            modules.append((self._gate_module, LifecyclePhase.PROACTIVE_GATE, 0))
        if self._fetch_module:
            modules.append((self._fetch_module, LifecyclePhase.PROACTIVE_FETCH, 0))
        if self._judge_module:
            modules.append((self._judge_module, LifecyclePhase.PROACTIVE_JUDGE, 0))
        if self._resolve_module:
            modules.append((self._resolve_module, LifecyclePhase.PROACTIVE_RESOLVE, 0))
        if self._deliver_module:
            modules.append((self._deliver_module, LifecyclePhase.PROACTIVE_DELIVER, 0))
        return modules

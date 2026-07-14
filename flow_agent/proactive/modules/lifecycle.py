"""模块生命周期管理。"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flow_agent.proactive.modules.base import ProactiveModule
    from flow_agent.proactive.modules.context import ModuleContext


class ModuleState(Enum):
    """模块状态。"""
    UNINITIALIZED = "uninitialized"
    INITIALIZED = "initialized"
    STARTED = "started"
    STOPPED = "stopped"
    CLEANED = "cleaned"
    ERROR = "error"


class ModuleLifecycle:
    """模块生命周期管理器。

    负责管理模块的初始化、启动、停止和清理过程。
    """

    def __init__(self, module: ProactiveModule):
        self._module = module
        self._state = ModuleState.UNINITIALIZED
        self._error: Exception | None = None

    @property
    def state(self) -> ModuleState:
        """当前模块状态。"""
        return self._state

    @property
    def error(self) -> Exception | None:
        """模块错误信息。"""
        return self._error

    @property
    def module(self) -> ProactiveModule:
        """关联的模块。"""
        return self._module

    async def initialize(self, context: ModuleContext) -> None:
        """初始化模块。"""
        if self._state != ModuleState.UNINITIALIZED:
            return
        
        try:
            await self._module.initialize(context)
            self._state = ModuleState.INITIALIZED
        except Exception as e:
            self._state = ModuleState.ERROR
            self._error = e
            raise

    async def start(self, context: ModuleContext) -> None:
        """启动模块。"""
        if self._state == ModuleState.STARTED:
            return
        
        if self._state != ModuleState.INITIALIZED:
            raise RuntimeError(f"模块未初始化: {self._module.spec.id}")
        
        try:
            await self._module.start(context)
            self._state = ModuleState.STARTED
        except Exception as e:
            self._state = ModuleState.ERROR
            self._error = e
            raise

    async def stop(self, context: ModuleContext) -> None:
        """停止模块。"""
        if self._state == ModuleState.STOPPED or self._state == ModuleState.UNINITIALIZED:
            return
        
        try:
            await self._module.stop(context)
            self._state = ModuleState.STOPPED
        except Exception as e:
            self._state = ModuleState.ERROR
            self._error = e
            raise

    async def cleanup(self, context: ModuleContext) -> None:
        """清理模块资源。"""
        if self._state == ModuleState.CLEANED:
            return
        
        try:
            await self._module.cleanup(context)
            self._state = ModuleState.CLEANED
        except Exception as e:
            self._state = ModuleState.ERROR
            self._error = e
            raise

    def is_active(self) -> bool:
        """检查模块是否活跃。"""
        return self._state == ModuleState.STARTED

    def is_healthy(self) -> bool:
        """检查模块是否健康。"""
        return self._state != ModuleState.ERROR

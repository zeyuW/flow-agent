"""主动回复模块基类和规范。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from flow_agent.proactive.modules.context import ModuleContext


@dataclass
class ProactiveModuleSpec:
    """主动回复模块规范。"""
    id: str
    name: str
    description: str
    slot: str = ""
    requires: tuple[str, ...] = field(default_factory=tuple)
    produces: tuple[str, ...] = field(default_factory=tuple)


class ProactiveModule(ABC):
    """主动回复模块基类。

    模块可以自定义主动回复的各个阶段行为：
    - Gate: 控制是否执行主动回复
    - Fetch: 获取数据源
    - Judge: 判断是否需要发送消息
    - Resolve: 决定最终发送内容
    - Deliver: 发送消息
    """

    def __init__(self, spec: ProactiveModuleSpec):
        self.spec = spec
        self._initialized = False
        self._started = False

    @property
    def slot(self) -> str:
        """模块槽位，用于依赖管理。"""
        return self.spec.slot

    @property
    def requires(self) -> tuple[str, ...]:
        """模块依赖的其他槽位。"""
        return self.spec.requires

    @property
    def produces(self) -> tuple[str, ...]:
        """模块产生的槽位。"""
        return self.spec.produces

    async def initialize(self, context: ModuleContext) -> None:
        """初始化模块。"""
        if self._initialized:
            return
        await self._on_initialize(context)
        self._initialized = True

    async def start(self, context: ModuleContext) -> None:
        """启动模块。"""
        if not self._initialized:
            raise RuntimeError(f"模块未初始化: {self.spec.id}")
        if self._started:
            return
        await self._on_start(context)
        self._started = True

    async def stop(self, context: ModuleContext) -> None:
        """停止模块。"""
        if not self._started:
            return
        await self._on_stop(context)
        self._started = False

    async def cleanup(self, context: ModuleContext) -> None:
        """清理模块资源。"""
        if self._started:
            await self.stop(context)
        if self._initialized:
            await self._on_cleanup(context)
            self._initialized = False

    @abstractmethod
    async def run(self, context: ModuleContext) -> ModuleContext:
        """执行模块逻辑。"""
        pass

    async def _on_initialize(self, context: ModuleContext) -> None:
        """初始化钩子，子类可重写。"""
        pass

    async def _on_start(self, context: ModuleContext) -> None:
        """启动钩子，子类可重写。"""
        pass

    async def _on_stop(self, context: ModuleContext) -> None:
        """停止钩子，子类可重写。"""
        pass

    async def _on_cleanup(self, context: ModuleContext) -> None:
        """清理钩子，子类可重写。"""
        pass

    def is_active(self) -> bool:
        """检查模块是否处于活跃状态。"""
        return self._initialized and self._started

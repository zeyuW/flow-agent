"""主动回复插件化架构接口。

提供简化的插件接口，支持自定义主动回复模块。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from application.proactive.domain.models import JudgeResult, ResolveResult


@dataclass
class ProactiveModuleSpec:
    """主动回复模块规范。"""
    id: str
    name: str
    description: str


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

    @abstractmethod
    async def run(self, context: ProactiveContext) -> ProactiveContext:
        """执行模块逻辑。"""
        pass


@dataclass
class ProactiveContext:
    """主动回复上下文。

    在各个模块之间传递数据。
    """
    chat_id: str
    is_busy: bool
    base_score: float
    raw_data: list[dict] | None = None
    judge_result: JudgeResult | None = None
    resolve_result: ResolveResult | None = None
    metadata: dict[str, Any] | None = None

    def with_data(self, **kwargs) -> "ProactiveContext":
        """更新上下文数据。"""
        return ProactiveContext(
            chat_id=self.chat_id,
            is_busy=self.is_busy,
            base_score=self.base_score,
            raw_data=self.raw_data,
            judge_result=self.judge_result,
            resolve_result=self.resolve_result,
            metadata={**(self.metadata or {}), **kwargs}
        )


class ProactivePlugin(ABC):
    """主动回复插件基类。

    插件可以提供多个模块，并定义模块的执行顺序。
    """

    @abstractmethod
    def get_modules(self) -> list[ProactiveModule]:
        """获取插件提供的所有模块。"""
        pass

    @abstractmethod
    def get_module_order(self) -> list[str]:
        """获取模块执行顺序（模块ID列表）。"""
        pass


class ProactivePluginRegistry:
    """主动回复插件注册表。"""

    def __init__(self):
        self._plugins: dict[str, ProactivePlugin] = {}
        self._modules: dict[str, ProactiveModule] = {}

    def register_plugin(self, plugin: ProactivePlugin) -> None:
        """注册插件。"""
        plugin_id = plugin.__class__.__name__
        self._plugins[plugin_id] = plugin
        
        for module in plugin.get_modules():
            self._modules[module.spec.id] = module

    def get_plugin(self, plugin_id: str) -> ProactivePlugin | None:
        """获取插件。"""
        return self._plugins.get(plugin_id)

    def get_module(self, module_id: str) -> ProactiveModule | None:
        """获取模块。"""
        return self._application.get(module_id)

    def get_all_modules(self) -> dict[str, ProactiveModule]:
        """获取所有模块。"""
        return self._application.copy()

    def get_execution_order(self, plugin_id: str) -> list[ProactiveModule]:
        """获取插件的模块执行顺序。"""
        plugin = self.get_plugin(plugin_id)
        if plugin is None:
            return []
        
        order = plugin.get_module_order()
        modules = []
        for module_id in order:
            module = self.get_module(module_id)
            if module:
                modules.append(module)
        return modules


# 全局插件注册表实例
_global_registry = ProactivePluginRegistry()


def register_plugin(plugin: ProactivePlugin) -> None:
    """注册插件到全局注册表。"""
    _global_registry.register_plugin(plugin)


def get_global_registry() -> ProactivePluginRegistry:
    """获取全局插件注册表。"""
    return _global_registry

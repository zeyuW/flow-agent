"""模块注册表。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flow_agent.proactive.modules.base import ProactiveModule


class ModuleRegistry:
    """模块注册表。

    管理所有注册的模块实例。
    """

    def __init__(self):
        self._modules: dict[str, ProactiveModule] = {}

    def register(self, module: ProactiveModule) -> None:
        """注册模块。"""
        module_id = module.spec.id
        if module_id in self._modules:
            raise ValueError(f"模块已注册: {module_id}")
        self._modules[module_id] = module

    def unregister(self, module_id: str) -> None:
        """注销模块。"""
        self._modules.pop(module_id, None)

    def get(self, module_id: str) -> ProactiveModule | None:
        """获取模块。"""
        return self._modules.get(module_id)

    def get_all(self) -> dict[str, ProactiveModule]:
        """获取所有模块。"""
        return self._modules.copy()

    def clear(self) -> None:
        """清空注册表。"""
        self._modules.clear()

    def __contains__(self, module_id: str) -> bool:
        """检查模块是否已注册。"""
        return module_id in self._modules

    def __len__(self) -> int:
        """获取注册模块数量。"""
        return len(self._modules)


# 全局模块注册表
_global_registry = ModuleRegistry()


def get_global_registry() -> ModuleRegistry:
    """获取全局模块注册表。"""
    return _global_registry

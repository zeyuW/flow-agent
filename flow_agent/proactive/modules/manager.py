"""模块管理器，负责协调模块生命周期和执行顺序。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from flow_agent.proactive.modules.registry import ModuleRegistry

if TYPE_CHECKING:
    from flow_agent.proactive.modules.base import ProactiveModule
    from flow_agent.proactive.modules.context import ModuleContext
    from flow_agent.proactive.modules.lifecycle import ModuleLifecycle


logger = logging.getLogger(__name__)


class ModuleManager:
    """模块管理器。

    负责模块的注册、初始化、启动、停止和执行协调。
    """

    def __init__(self, registry: ModuleRegistry | None = None):
        self._registry = registry or ModuleRegistry()
        self._lifecycles: dict[str, ModuleLifecycle] = {}
        self._execution_order: list[str] = []
        self._initialized = False

    @property
    def registry(self) -> ModuleRegistry:
        """模块注册表。"""
        return self._registry

    def register_module(self, module: ProactiveModule) -> None:
        """注册模块。"""
        self._registry.register(module)
        from flow_agent.proactive.modules.lifecycle import ModuleLifecycle
        self._lifecycles[module.spec.id] = ModuleLifecycle(module)
        self._invalidate_execution_order()

    def unregister_module(self, module_id: str) -> None:
        """注销模块。"""
        self._registry.unregister(module_id)
        self._lifecycles.pop(module_id, None)
        self._invalidate_execution_order()

    def get_module(self, module_id: str) -> ProactiveModule | None:
        """获取模块。"""
        return self._registry.get(module_id)

    def get_lifecycle(self, module_id: str) -> ModuleLifecycle | None:
        """获取模块生命周期。"""
        return self._lifecycles.get(module_id)

    def get_all_modules(self) -> dict[str, ProactiveModule]:
        """获取所有模块。"""
        return self._registry.get_all()

    def _invalidate_execution_order(self) -> None:
        """使执行顺序失效，下次使用时重新计算。"""
        self._execution_order = []
        self._initialized = False

    def _compute_execution_order(self) -> list[str]:
        """计算模块执行顺序（拓扑排序）。"""
        modules = self._registry.get_all()
        if not modules:
            return []

        # 构建依赖图
        graph: dict[str, set[str]] = {mid: set() for mid in modules}
        in_degree: dict[str, int] = {mid: 0 for mid in modules}

        for module_id, module in modules.items():
            for required in module.requires:
                if required in modules:
                    graph[required].add(module_id)
                    in_degree[module_id] += 1

        # 拓扑排序
        queue = [mid for mid, degree in in_degree.items() if degree == 0]
        order: list[str] = []

        while queue:
            current = queue.pop(0)
            order.append(current)

            for dependent in graph[current]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        # 检查循环依赖
        if len(order) != len(modules):
            remaining = set(modules.keys()) - set(order)
            raise RuntimeError(f"检测到循环依赖: {remaining}")

        return order

    def get_execution_order(self) -> list[str]:
        """获取模块执行顺序。"""
        if not self._execution_order:
            self._execution_order = self._compute_execution_order()
        return self._execution_order.copy()

    async def initialize_all(self, context: ModuleContext) -> None:
        """初始化所有模块。"""
        if self._initialized:
            return

        order = self.get_execution_order()
        for module_id in order:
            lifecycle = self._lifecycles.get(module_id)
            if lifecycle:
                try:
                    await lifecycle.initialize(context)
                    logger.info(f"模块初始化成功: {module_id}")
                except Exception as e:
                    logger.error(f"模块初始化失败: {module_id}, error: {e}")
                    raise

        self._initialized = True

    async def start_all(self, context: ModuleContext) -> None:
        """启动所有模块。"""
        if not self._initialized:
            await self.initialize_all(context)

        order = self.get_execution_order()
        for module_id in order:
            lifecycle = self._lifecycles.get(module_id)
            if lifecycle:
                try:
                    await lifecycle.start(context)
                    logger.info(f"模块启动成功: {module_id}")
                except Exception as e:
                    logger.error(f"模块启动失败: {module_id}, error: {e}")
                    raise

    async def stop_all(self, context: ModuleContext) -> None:
        """停止所有模块（逆序）。"""
        order = list(reversed(self.get_execution_order()))
        for module_id in order:
            lifecycle = self._lifecycles.get(module_id)
            if lifecycle:
                try:
                    await lifecycle.stop(context)
                    logger.info(f"模块停止成功: {module_id}")
                except Exception as e:
                    logger.error(f"模块停止失败: {module_id}, error: {e}")

    async def cleanup_all(self, context: ModuleContext) -> None:
        """清理所有模块资源（逆序）。"""
        order = list(reversed(self.get_execution_order()))
        for module_id in order:
            lifecycle = self._lifecycles.get(module_id)
            if lifecycle:
                try:
                    await lifecycle.cleanup(context)
                    logger.info(f"模块清理成功: {module_id}")
                except Exception as e:
                    logger.error(f"模块清理失败: {module_id}, error: {e}")

        self._initialized = False

    async def execute_pipeline(self, context: ModuleContext) -> ModuleContext:
        """执行模块管道。"""
        if not self._initialized:
            await self.initialize_all(context)

        order = self.get_execution_order()
        for module_id in order:
            lifecycle = self._lifecycles.get(module_id)
            if lifecycle and lifecycle.is_active():
                try:
                    module = lifecycle.module
                    context = await module.run(context)
                    logger.debug(f"模块执行成功: {module_id}")
                except Exception as e:
                    logger.error(f"模块执行失败: {module_id}, error: {e}")
                    raise

        return context

    def get_active_modules(self) -> list[str]:
        """获取活跃模块列表。"""
        return [
            module_id
            for module_id, lifecycle in self._lifecycles.items()
            if lifecycle.is_active()
        ]

    def get_healthy_modules(self) -> list[str]:
        """获取健康模块列表。"""
        return [
            module_id
            for module_id, lifecycle in self._lifecycles.items()
            if lifecycle.is_healthy()
        ]

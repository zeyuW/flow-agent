"""模块工厂，用于构建和注册主动回复模块。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from flow_agent.proactive.modules.base import ProactiveModule
from flow_agent.proactive.modules.gate_module import GateModule
from flow_agent.proactive.modules.fetch_module import FetchModule
from flow_agent.proactive.modules.judge_module import JudgeModule
from flow_agent.proactive.modules.resolve_module import ResolveModule
from flow_agent.proactive.modules.deliver_module import DeliverModule

if TYPE_CHECKING:
    from flow_agent.proactive.modules.manager import ModuleManager


class ProactiveModuleFactory:
    """主动回复模块工厂。"""

    def __init__(self):
        self._data_gateway = None
        self._judge_loop = None
        self._state_store = None
        self._message_bus = None

    def set_data_gateway(self, data_gateway) -> ProactiveModuleFactory:
        """设置数据网关。"""
        self._data_gateway = data_gateway
        return self

    def set_judge_loop(self, judge_loop) -> ProactiveModuleFactory:
        """设置 Judge 循环。"""
        self._judge_loop = judge_loop
        return self

    def set_state_store(self, state_store) -> ProactiveModuleFactory:
        """设置状态存储。"""
        self._state_store = state_store
        return self

    def set_message_bus(self, message_bus) -> ProactiveModuleFactory:
        """设置消息总线。"""
        self._message_bus = message_bus
        return self

    def create_gate_module(self, max_per_day: int = 5) -> GateModule:
        """创建 Gate 模块。"""
        return GateModule(max_per_day=max_per_day)

    def create_fetch_module(self) -> FetchModule:
        """创建 Fetch 模块。"""
        return FetchModule(data_gateway=self._data_gateway)

    def create_judge_module(self) -> JudgeModule:
        """创建 Judge 模块。"""
        return JudgeModule(judge_loop=self._judge_loop)

    def create_resolve_module(self) -> ResolveModule:
        """创建 Resolve 模块。"""
        return ResolveModule(state_store=self._state_store)

    def create_deliver_module(self) -> DeliverModule:
        """创建 Deliver 模块。"""
        return DeliverModule(message_bus=self._message_bus)

    def build_default_pipeline(self, manager: ModuleManager) -> None:
        """构建默认的主动回复管道。"""
        # 创建并注册模块
        gate = self.create_gate_module()
        fetch = self.create_fetch_module()
        judge = self.create_judge_module()
        resolve = self.create_resolve_module()
        deliver = self.create_deliver_module()

        # 注册到管理器
        manager.register_module(gate)
        manager.register_module(fetch)
        manager.register_module(judge)
        manager.register_module(resolve)
        manager.register_module(deliver)


def create_module_factory() -> ProactiveModuleFactory:
    """创建模块工厂实例。"""
    return ProactiveModuleFactory()

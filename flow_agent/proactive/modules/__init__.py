"""主动回复插件模块目录。

统一管理主动回复模块的生命周期和行为。
"""

from flow_agent.proactive.modules.base import ProactiveModule, ProactiveModuleSpec
from flow_agent.proactive.modules.manager import ModuleManager
from flow_agent.proactive.modules.registry import ModuleRegistry
from flow_agent.proactive.modules.lifecycle import ModuleLifecycle, ModuleState
from flow_agent.proactive.modules.context import ModuleContext
from flow_agent.proactive.modules.factory import ProactiveModuleFactory, create_module_factory
from flow_agent.proactive.modules.gate_module import GateModule
from flow_agent.proactive.modules.fetch_module import FetchModule
from flow_agent.proactive.modules.judge_module import JudgeModule
from flow_agent.proactive.modules.resolve_module import ResolveModule
from flow_agent.proactive.modules.deliver_module import DeliverModule

__all__ = [
    "ProactiveModule",
    "ProactiveModuleSpec",
    "ModuleManager",
    "ModuleRegistry",
    "ModuleLifecycle",
    "ModuleState",
    "ModuleContext",
    "ProactiveModuleFactory",
    "create_module_factory",
    "GateModule",
    "FetchModule",
    "JudgeModule",
    "ResolveModule",
    "DeliverModule",
]

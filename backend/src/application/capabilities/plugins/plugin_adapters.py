"""插件贡献适配器。

本模块把插件声明转换为宿主运行时需要的工具、事件订阅、主动来源和后台作业，
不负责插件发现、版本计算或代际发布。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from application.capabilities.mcp.config import McpServerSpec
from application.automation.domain.models import JobSpec
from application.capabilities.plugins.plugin_base import Plugin

logger = logging.getLogger(__name__)


def resolve_mcp_spec(
    plugin_name: str,
    spec: McpServerSpec,
    plugin_dir,
    data_dir,
) -> McpServerSpec:
    """将插件声明的 MCP 路径解析为宿主可启动的绝对路径。"""

    if not isinstance(spec, McpServerSpec):
        raise TypeError(f"插件 {plugin_name} 返回了无效的 MCP 声明")
    return spec.with_plugin_paths(plugin_dir, data_dir)


def collect_phase_modules(instance: Plugin) -> list[Any]:
    """按被动回合顺序收集插件声明的阶段模块。"""

    modules: list[Any] = []
    for method_name in (
        "turn_started_modules",
        "before_turn_modules",
        "before_reasoning_modules",
        "prompt_render_modules",
        "reasoner_modules",
        "after_reasoning_modules",
        "after_turn_modules",
    ):
        for module in getattr(instance, method_name)() or []:
            if module not in modules:
                modules.append(module)
    return modules


def collect_proactive_sources(instance: Plugin, plugin_name: str) -> list[Any]:
    """将插件主动信息源绑定到插件身份。"""

    sources = instance.proactive_sources() or []
    if not sources:
        return []
    from application.capabilities.plugins.proactive import RegisteredProactiveSource

    return [
        RegisteredProactiveSource(spec=spec, plugin_id=plugin_name)
        for spec in sources
    ]


def collect_proactive_modules(instance: Plugin) -> list[Any]:
    """读取插件主动扩展模块。"""

    return list(instance.proactive_modules() or [])


def collect_background_jobs(instance: Plugin, plugin_name: str) -> list[JobSpec]:
    """校验插件声明的后台作业。"""

    jobs = instance.background_jobs() or []
    if not all(isinstance(job, JobSpec) for job in jobs):
        raise TypeError(f"插件 {plugin_name} 返回了无效的后台任务")
    return list(jobs)


class DynamicPluginTool:
    """把插件方法适配为宿主工具协议。"""

    def __init__(self, name: str, description: str, schema: dict | None, execute_fn) -> None:
        self._name = name
        self._description = description
        self._schema = schema or {}
        self._execute = execute_fn

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict:
        return self._schema

    def run(self, tool_input: dict):
        from application.capabilities.tools.base import ToolResult

        try:
            result = self._execute(**tool_input)
            if asyncio.iscoroutine(result):
                result = asyncio.run(result)
            return ToolResult(ok=True, content=str(result))
        except Exception as exc:
            return ToolResult(ok=False, content=f"插件工具执行失败: {exc}")


class PluginEventSubscriber:
    """只向匹配事件类型的插件生命周期处理器分发事件。"""

    def __init__(self, handler, event_type: str) -> None:
        self.handler = handler
        self.event_type = event_type

    def on_event(self, event) -> None:
        if getattr(event, "event_type", "") != self.event_type:
            return
        try:
            result = self.handler(ctx=event)
            if asyncio.iscoroutine(result):
                asyncio.run(result)
        except Exception:
            logger.exception("插件生命周期处理器执行失败: %s", self.event_type)

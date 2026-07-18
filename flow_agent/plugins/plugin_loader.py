"""插件管理器：发现、导入、绑定、初始化并在失败时回滚。"""

import functools
import importlib.util
import logging
from pathlib import Path
from typing import Any

from flow_agent.mcp.config import McpServerSpec
from flow_agent.plugins.plugin_base import Plugin
from flow_agent.plugins.plugin_context import PluginContext
from flow_agent.plugins.plugin_registry import (
    HandlerMeta,
    MetadataKind,
    PluginRegistry,
    ToolMeta,
    plugin_registry,
)
from flow_agent.plugins.tool_hooks import ToolHookExecutor, _PluginToolHook

logger = logging.getLogger(__name__)


class PluginManager:
    """运行时插件管理器，统一编译并绑定插件能力。"""

    def __init__(
        self,
        plugins_dir: Path,
        *,
        event_bus=None,
        tool_registry=None,
        workspace: Path | None = None,
        plugin_data_dir: Path | None = None,
    ) -> None:
        self._dir = plugins_dir
        self._event_bus = event_bus
        self._tool_registry = tool_registry
        self._workspace = workspace
        self._plugin_data_dir = plugin_data_dir or (
            workspace / "plugin-data" if workspace is not None else None
        )
        self._loaded: dict[str, Plugin] = {}
        self._tool_names: dict[str, list[str]] = {}  # 记录模块绑定的工具名称
        self._tool_hook_executor = ToolHookExecutor()
        self._proactive_sources: dict[str, list] = {}  # 按插件标识保存主动信息源
        self._mcp_servers: list[McpServerSpec] = []

    @property
    def tool_hook_executor(self) -> ToolHookExecutor:
        return self._tool_hook_executor

    def get_proactive_sources(self) -> dict[str, list]:
        """获取所有插件的主动推送数据源声明"""
        return self._proactive_sources

    def get_mcp_servers(self) -> list[McpServerSpec]:
        """返回所有已加载插件解析后的 MCP 服务声明。"""
        return list(self._mcp_servers)

    # ── 发现 ──

    def discover(self) -> list[dict[str, str]]:
        """扫描包含 plugin.py 的插件子目录。"""
        if not self._dir.exists():
            return []
        results: list[dict[str, str]] = []
        for d in sorted(self._dir.iterdir()):
            if not d.is_dir():
                continue
            if (d / "plugin.py").exists():
                results.append({"name": d.name, "path": str(d)})
        return results

    # ── 批量加载 ──

    async def load_all(self) -> None:
        """发现并加载全部可用插件。"""
        for mod in self.discover():
            try:
                await self._load_one(mod)
            except Exception:
                logger.exception("plugin load failed: %s", mod["name"])

    async def shutdown_all(self) -> None:
        """按加载逆序关闭插件，并释放其运行时资源。"""
        for name, instance in reversed(list(self._loaded.items())):
            try:
                await instance.shutdown()
            except Exception:
                logger.exception("插件关闭失败: %s", name)
        self._loaded.clear()
        self._mcp_servers.clear()

    # ── 单插件加载与回滚 ──

    async def _load_one(self, mod: dict[str, str]) -> None:
        """幂等执行启用检查、导入、实例化、绑定和初始化。"""
        name = mod["name"]
        pdir = Path(mod["path"])

        if (pdir / "plugin.disabled").exists() or name in self._loaded:
            return

        # 动态导入会触发插件类和装饰器元数据的自动注册。
        module = _import_module(pdir / "plugin.py", f"plugins.{name}")

        # 从本次导入产生的注册结果中取得插件类。
        cls_name = _find_plugin_class(module, name)
        if cls_name is None:
            logger.warning("no Plugin subclass found in %s", name)
            return
        cls = plugin_registry.pop_class(cls_name)
        if cls is None:
            return

        # 实例化后注入宿主资源与插件私有目录。
        instance = cls()
        instance._inject_context(
            PluginContext(
                event_bus=self._event_bus,
                tool_registry=self._tool_registry,
                workspace=self._workspace,
                data_dir=(self._plugin_data_dir / name) if self._plugin_data_dir else None,
            ),
            pdir,
        )

        plugin_data_dir = (
            self._plugin_data_dir / name
            if self._plugin_data_dir is not None
            else pdir
        )
        resolved_mcp_specs: list[McpServerSpec] = []
        for spec in instance.mcp_servers():
            if not isinstance(spec, McpServerSpec):
                raise TypeError(f"插件 {name} 返回了无效的 MCP 声明")
            resolved_mcp_specs.append(
                spec.with_plugin_paths(pdir, plugin_data_dir)
            )

        # 绑定生命周期处理器、工具和工具钩子。
        handlers = plugin_registry.pop_handlers()
        tools = plugin_registry.pop_tools()
        self._bind_handlers(instance, name, handlers)
        self._bind_tools(instance, name, tools)
        self._bind_tool_hooks(instance, name, handlers)

        # 收集插件声明的主动信息源。
        if hasattr(instance, "proactive_sources"):
            proactive_sources = instance.proactive_sources()
            if proactive_sources:
                from flow_agent.proactive.specs import RegisteredProactiveSource
                registered = [
                    RegisteredProactiveSource(spec=spec, plugin_id=name)
                    for spec in proactive_sources
                ]
                self._proactive_sources[name] = registered
                logger.info("plugin %s registered %d proactive sources", name, len(registered))

        # 异步初始化失败时撤销此前绑定的能力。
        try:
            if hasattr(instance, "initialize"):
                await instance.initialize()
        except Exception:
            logger.exception("plugin init failed, rolling back: %s", name)
            self._rollback(instance, name, tools)
            return

        self._mcp_servers.extend(resolved_mcp_specs)

        self._loaded[name] = instance
        logger.info("plugin loaded: %s", name)

    # ── 生命周期事件绑定 ──

    def _bind_handlers(self, instance: Plugin, module_path: str, metas: list[HandlerMeta]) -> None:
        """把插件生命周期处理器注册到事件总线。"""
        if self._event_bus is None:
            return
        for md in metas:
            if md.kind != MetadataKind.LIFECYCLE:
                continue
            bound = functools.partial(md.handler, instance)
            self._event_bus.subscribe(_EventSub(bound, md.event_type))

    # ── 工具钩子绑定 ──

    def _bind_tool_hooks(self, instance: Plugin, module_path: str, metas: list[HandlerMeta]) -> None:
        """把插件工具钩子处理器转换为宿主适配器。"""
        for md in metas:
            if md.kind != MetadataKind.TOOL_HOOK:
                continue
            bound_handler = functools.partial(md.handler, instance)
            hook = _PluginToolHook(
                tool_name=md.tool_name,
                priority=md.priority,
                handler=lambda ctx, h=bound_handler: h(ctx),
            )
            self._tool_hook_executor.register(hook)

    # ── 工具注册 ──

    def _bind_tools(self, instance: Plugin, module_path: str, metas: list[ToolMeta]) -> None:
        """为装饰器工具创建动态适配器并注册到工具表。"""
        if self._tool_registry is None:
            return
        names: list[str] = []
        for tm in metas:
            # 每个处理器独立包装，避免插件实现依赖宿主工具基类。
            bound = functools.partial(tm.handler, instance)
            tool_inst = _DynamicTool(
                name=tm.name,
                description=tm.description,
                schema=tm.schema,
                execute_fn=bound,
            )
            self._tool_registry.register_with_meta(
                tool_inst,
                risk="external-side-effect",
                source_type="plugin",
                source_name=module_path,
            )
            names.append(tm.name)
        self._tool_names[module_path] = names

    # ── 回滚 ──

    def _rollback(self, instance: Plugin, module_path: str, tools: list[ToolMeta]) -> None:
        """初始化失败时注销工具并清理钩子。"""
        for name in self._tool_names.pop(module_path, []):
            if self._tool_registry and hasattr(self._tool_registry, "unregister"):
                self._tool_registry.unregister(name)
        for tm in tools:
            plugin_registry.add_tool(tm)  # 放回注册池供后续重试
        self._tool_hook_executor.unregister_all()


# ── 辅助函数 ──

def _import_module(filepath: Path, modname: str):
    spec = importlib.util.spec_from_file_location(modname, filepath)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {filepath}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _find_plugin_class(module, dirname: str) -> str | None:
    for attr in dir(module):
        obj = getattr(module, attr)
        if isinstance(obj, type) and issubclass(obj, Plugin) and obj is not Plugin:
            return attr
    return None


# ── 动态工具包装器 ──

class _DynamicTool:
    """为插件装饰器方法创建的工具实例。"""

    def __init__(self, name: str, description: str, schema: dict | None, execute_fn) -> None:
        self._name = name
        self._desc = description
        self._schema = schema or {}
        self._fn = execute_fn

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._desc

    @property
    def input_schema(self) -> dict:
        return self._schema

    def run(self, tool_input: dict):
        from flow_agent.tools.base import ToolResult
        import asyncio
        try:
            result = self._fn(**tool_input)
            if asyncio.iscoroutine(result):
                result = asyncio.run(result)
            return ToolResult(ok=True, content=str(result))
        except Exception as exc:
            return ToolResult(ok=False, content=f"plugin tool error: {exc}")


# ── 事件订阅适配器 ──

class _EventSub:
    def __init__(self, handler, event_type: str):
        self.handler = handler
        self.event_type = event_type

    def on_event(self, event) -> None:
        import asyncio
        try:
            result = self.handler(ctx=event)
            if asyncio.iscoroutine(result):
                asyncio.run(result)
        except Exception:
            logger.exception("plugin event handler failed")

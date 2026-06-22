"""PluginManager: discover, dynamic import, instantiate, bind, init with rollback (spec 1)."""

import functools
import importlib.util
import logging
from pathlib import Path
from typing import Any

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
    """Runtime plugin manager: discover, load, bind, init with rollback (spec 1)."""

    def __init__(
        self,
        plugins_dir: Path,
        *,
        event_bus=None,
        tool_registry=None,
        workspace: Path | None = None,
    ) -> None:
        self._dir = plugins_dir
        self._event_bus = event_bus
        self._tool_registry = tool_registry
        self._workspace = workspace
        self._loaded: dict[str, Plugin] = {}
        self._tool_names: dict[str, list[str]] = {}  # module_path -> tool names
        self._tool_hook_executor = ToolHookExecutor()

    @property
    def tool_hook_executor(self) -> ToolHookExecutor:
        return self._tool_hook_executor

    # ── Discovery (spec 1a) ──

    def discover(self) -> list[dict[str, str]]:
        """Scan plugins_dir for subdirs containing plugin.py (spec 1a)."""
        if not self._dir.exists():
            return []
        results: list[dict[str, str]] = []
        for d in sorted(self._dir.iterdir()):
            if not d.is_dir():
                continue
            if (d / "plugin.py").exists():
                results.append({"name": d.name, "path": str(d)})
        return results

    # ── Load all ──

    async def load_all(self) -> None:
        """Discover and load all plugins."""
        for mod in self.discover():
            try:
                await self._load_one(mod)
            except Exception:
                logger.exception("plugin load failed: %s", mod["name"])

    # ── Load single with rollback (spec 1b-1e) ──

    async def _load_one(self, mod: dict[str, str]) -> None:
        """Idempotent load: check disabled, import, instantiate, bind, init (spec 1b)."""
        name = mod["name"]
        pdir = Path(mod["path"])

        if (pdir / "plugin.disabled").exists() or name in self._loaded:
            return

        # 1c: Dynamic import triggers auto-registration
        module = _import_module(pdir / "plugin.py", f"plugins.{name}")

        # Get the registered Plugin subclass
        cls_name = _find_plugin_class(module, name)
        if cls_name is None:
            logger.warning("no Plugin subclass found in %s", name)
            return
        cls = plugin_registry.pop_class(cls_name)
        if cls is None:
            return

        # 1d: Instantiate and inject context
        instance = cls()
        instance._inject_context(
            PluginContext(
                event_bus=self._event_bus,
                tool_registry=self._tool_registry,
                workspace=self._workspace,
            ),
            pdir,
        )

        # Bind handlers, tools, hooks
        handlers = plugin_registry.pop_handlers()
        tools = plugin_registry.pop_tools()
        self._bind_handlers(instance, name, handlers)
        self._bind_tools(instance, name, tools)
        self._bind_tool_hooks(instance, name, handlers)

        # 1e: Async init with rollback
        try:
            if hasattr(instance, "initialize"):
                await instance.initialize()
        except Exception:
            logger.exception("plugin init failed, rolling back: %s", name)
            self._rollback(instance, name, tools)
            return

        self._loaded[name] = instance
        logger.info("plugin loaded: %s", name)

    # ── Bind handlers to EventBus (spec 3c-3d) ──

    def _bind_handlers(self, instance: Plugin, module_path: str, metas: list[HandlerMeta]) -> None:
        """Register lifecycle handlers to EventBus (spec 3c)."""
        if self._event_bus is None:
            return
        for md in metas:
            if md.kind != MetadataKind.LIFECYCLE:
                continue
            bound = functools.partial(md.handler, instance)
            self._event_bus.subscribe(_EventSub(bound, md.event_type))

    # ── Bind tool hooks (spec 4b) ──

    def _bind_tool_hooks(self, instance: Plugin, module_path: str, metas: list[HandlerMeta]) -> None:
        """Create _PluginToolHook adapters from TOOL_HOOK handlers (spec 4b)."""
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

    # ── Register tools (spec 5c-5e) ──

    def _bind_tools(self, instance: Plugin, module_path: str, metas: list[ToolMeta]) -> None:
        """Dynamic Tool subclass creation and ToolRegistry registration (spec 5c-5e)."""
        if self._tool_registry is None:
            return
        names: list[str] = []
        for tm in metas:
            # 5d: dynamic Tool subclass
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

    # ── Rollback (spec 1e) ──

    def _rollback(self, instance: Plugin, module_path: str, tools: list[ToolMeta]) -> None:
        """Unregister tools and clear hooks on init failure."""
        for name in self._tool_names.pop(module_path, []):
            if self._tool_registry and hasattr(self._tool_registry, "unregister"):
                self._tool_registry.unregister(name)
        for tm in tools:
            plugin_registry.add_tool(tm)  # return to pool
        self._tool_hook_executor.unregister_all()


# ── Helpers ──

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


# ── Dynamic tool wrapper (spec 5d) ──

class _DynamicTool:
    """Tool instance created for @tool-decorated plugin methods (spec 5d)."""

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


# ── EventSubscriber adapter ──

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

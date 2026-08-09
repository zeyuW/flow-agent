"""插件运行时：发现、候选准备、能力发布和文件热重载。"""

from __future__ import annotations

import asyncio
import functools
import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from application.capabilities.mcp.config import McpServerSpec
from application.automation.domain.models import JobSpec
from application.capabilities.plugins.plugin_base import Plugin
from application.capabilities.plugins.plugin_context import PluginContext
from application.capabilities.plugins.plugin_registry import (
    HandlerMeta,
    MetadataKind,
    ToolMeta,
    plugin_registry,
)
from application.capabilities.plugins.tool_hooks import ToolHookExecutor, _PluginToolHook
from application.capabilities.plugins.plugin_adapters import (
    DynamicPluginTool,
    PluginEventSubscriber,
    collect_background_jobs,
    collect_phase_modules,
    collect_proactive_modules,
    collect_proactive_sources,
    resolve_mcp_spec,
)
from application.capabilities.plugins.plugin_runtime import (
    discard_modules as _discard_modules,
    find_plugin_class as _find_plugin_class,
    import_module as _import_module,
    plugin_revision as _plugin_revision,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _PreparedPlugin:
    """尚未对外发布的一代插件贡献。"""

    name: str
    plugin_dir: Path
    revision: str
    module_name: str
    instance: Plugin
    handlers: list[HandlerMeta]
    tools: list[ToolMeta]
    phase_modules: list[Any]
    proactive_modules: list[Any]
    proactive_sources: list[Any]
    mcp_servers: list[McpServerSpec]
    background_jobs: list[JobSpec]


@dataclass(slots=True)
class _ActivePlugin:
    """当前已经发布并可被运行时观察的一代插件。"""

    prepared: _PreparedPlugin
    subscribers: list[Any] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)
    job_names: list[str] = field(default_factory=list)


class PluginManager:
    """把插件的一组运行时贡献作为一个热重载单元管理。"""

    def __init__(
        self,
        plugins_dir: Path,
        *,
        event_bus=None,
        tool_registry=None,
        background_registry=None,
        workspace: Path | None = None,
        plugin_data_dir: Path | None = None,
        on_contributions_changed: Callable[[], None] | None = None,
    ) -> None:
        self._dir = plugins_dir
        self._event_bus = event_bus
        self._tool_registry = tool_registry
        self._background_registry = background_registry
        self._workspace = workspace
        self._plugin_data_dir = plugin_data_dir or (
            workspace / "plugin-data" if workspace is not None else None
        )
        self._loaded: dict[str, _ActivePlugin] = {}
        self._failed_revisions: dict[str, str] = {}
        self._tool_hook_executor = ToolHookExecutor()
        self._on_contributions_changed = on_contributions_changed
        self._lock = threading.RLock()
        self._reconcile_lock = threading.Lock()
        self._watch_thread: threading.Thread | None = None
        self._watch_stop = threading.Event()

    @property
    def tool_hook_executor(self) -> ToolHookExecutor:
        return self._tool_hook_executor

    def set_contributions_callback(
        self,
        callback: Callable[[], None] | None,
    ) -> None:
        """设置插件代际发布后的宿主刷新回调。"""

        self._on_contributions_changed = callback

    def get_phase_modules(self) -> list[Any]:
        """返回当前插件代际的阶段模块快照。"""

        with self._lock:
            return [
                module
                for active in self._loaded.values()
                for module in active.prepared.phase_modules
            ]

    def get_proactive_sources(self) -> dict[str, list[Any]]:
        """返回当前插件代际的主动信息源。"""

        with self._lock:
            return {
                name: list(active.prepared.proactive_sources)
                for name, active in self._loaded.items()
                if active.prepared.proactive_sources
            }

    def get_proactive_modules(self) -> list[Any]:
        """返回当前插件代际声明的主动扩展模块快照。"""

        with self._lock:
            return [
                module
                for active in self._loaded.values()
                for module in active.prepared.proactive_modules
            ]

    def get_mcp_servers(self) -> list[McpServerSpec]:
        """返回当前插件代际解析后的 MCP 服务声明。"""

        with self._lock:
            return [
                spec
                for active in self._loaded.values()
                for spec in active.prepared.mcp_servers
            ]

    def discover(self) -> list[dict[str, str]]:
        """扫描包含 plugin.py 且未禁用的插件目录。"""

        if not self._dir.exists():
            return []
        return [
            {"name": path.name, "path": str(path)}
            for path in sorted(self._dir.iterdir())
            if path.is_dir()
            and (path / "plugin.py").is_file()
            and not (path / "plugin.disabled").exists()
        ]

    async def load_all(self) -> None:
        """根据同一个发现快照加载或更新全部插件。"""

        await self.reconcile()

    async def reconcile(self) -> bool:
        """准备变化候选；失败保留旧代，成功后发布新贡献。"""

        with self._reconcile_lock:
            return await self._reconcile_once()

    async def _reconcile_once(self) -> bool:
        """使用单个发现快照执行一轮串行代际协调。"""

        snapshot = {item["name"]: Path(item["path"]) for item in self.discover()}
        candidates: list[_PreparedPlugin] = []
        recovered = False
        for name in sorted(snapshot):
            plugin_dir = snapshot[name]
            data_dir = self._plugin_data_dir / name if self._plugin_data_dir else None
            revision = _plugin_revision(plugin_dir, data_dir)
            with self._lock:
                active = self._loaded.get(name)
            if active is not None and active.prepared.revision == revision:
                failed_revision = self._failed_revisions.pop(name, None)
                recovered = recovered or failed_revision is not None
                continue
            if self._failed_revisions.get(name) == revision:
                for prepared in reversed(candidates):
                    await self._discard_prepared(prepared)
                return False
            try:
                candidate = await self._prepare(name, plugin_dir, revision)
                candidates.append(candidate)
            except Exception:
                self._failed_revisions[name] = revision
                # 同一轮中任一候选失败时，不能让前面的候选形成半代发布。
                for prepared in reversed(candidates):
                    await self._discard_prepared(prepared)
                logger.exception("插件候选加载失败，保留当前完整运行时: %s", name)
                return False

        changed = False
        published: set[str] = set()
        try:
            for candidate in candidates:
                await self._publish(candidate)
                self._failed_revisions.pop(candidate.name, None)
                published.add(candidate.name)
                changed = True
        except Exception:
            # 发布期异常不应让尚未发布的候选泄漏模块或资源。
            for candidate in reversed(candidates):
                if candidate.name not in published:
                    await self._discard_prepared(candidate)
            raise

        with self._lock:
            removed = sorted(set(self._loaded) - set(snapshot))
        for name in removed:
            await self._unload(name)
            self._failed_revisions.pop(name, None)
            changed = True

        if changed and self._on_contributions_changed is not None:
            self._on_contributions_changed()
        return changed or recovered

    async def _discard_prepared(self, prepared: _PreparedPlugin) -> None:
        """释放本轮未发布候选，保持当前已发布插件不变。"""

        try:
            await prepared.instance.shutdown()
        except Exception:
            logger.exception("插件候选清理失败: %s", prepared.name)
        _discard_modules(prepared.module_name)

    async def shutdown_all(self) -> None:
        """停止 watcher，并按加载逆序关闭全部插件。"""

        self.stop_watcher()
        with self._lock:
            names = list(self._loaded)
        for name in reversed(names):
            await self._unload(name)

    def start_watcher(self, interval_seconds: float = 1.0) -> None:
        """启动插件代码与插件配置文件的轮询热重载。"""

        if self._watch_thread is not None and self._watch_thread.is_alive():
            return
        self._watch_stop.clear()

        def watch() -> None:
            while not self._watch_stop.wait(max(0.2, interval_seconds)):
                try:
                    asyncio.run(self.reconcile())
                except Exception:
                    logger.exception("插件热重载失败，继续使用当前代")

        self._watch_thread = threading.Thread(
            target=watch,
            name="plugin-config-watcher",
            daemon=True,
        )
        self._watch_thread.start()

    def stop_watcher(self) -> None:
        """停止并等待插件热重载线程退出。"""

        self._watch_stop.set()
        if self._watch_thread is not None:
            self._watch_thread.join(timeout=3.0)
            self._watch_thread = None

    async def _prepare(
        self,
        name: str,
        plugin_dir: Path,
        revision: str,
    ) -> _PreparedPlugin:
        """导入并初始化候选，但不注册任何公开能力。"""

        plugin_registry.clear()
        safe_name = re.sub(r"[^0-9A-Za-z_]", "_", name)
        module_name = f"flow_plugin_{safe_name}_{revision[:12]}"
        instance: Plugin | None = None
        try:
            module = _import_module(plugin_dir / "plugin.py", module_name, plugin_dir)
            handlers = plugin_registry.pop_handlers()
            tools = plugin_registry.pop_tools()
            cls = _find_plugin_class(module)
            if cls is None:
                raise ValueError(f"插件 {name} 未声明 Plugin 子类")
            instance = cls()
            data_dir = self._plugin_data_dir / name if self._plugin_data_dir else None
            instance._inject_context(
                PluginContext(
                    event_bus=self._event_bus,
                    tool_registry=self._tool_registry,
                    workspace=self._workspace,
                    data_dir=data_dir,
                ),
                plugin_dir,
            )
            mcp_servers = [
                resolve_mcp_spec(name, spec, plugin_dir, data_dir or plugin_dir)
                for spec in instance.mcp_servers()
            ]
            phase_modules = collect_phase_modules(instance)
            proactive_modules = collect_proactive_modules(instance)
            proactive_sources = collect_proactive_sources(instance, name)
            background_jobs = collect_background_jobs(instance, name)
            self._validate_names(name, tools, background_jobs)
            await instance.initialize()
            return _PreparedPlugin(
                name=name,
                plugin_dir=plugin_dir,
                revision=revision,
                module_name=module_name,
                instance=instance,
                handlers=handlers,
                tools=tools,
                phase_modules=phase_modules,
                proactive_modules=proactive_modules,
                proactive_sources=proactive_sources,
                mcp_servers=mcp_servers,
                background_jobs=background_jobs,
            )
        except Exception:
            if instance is not None:
                try:
                    await instance.shutdown()
                except Exception:
                    logger.exception("插件候选清理失败: %s", name)
            _discard_modules(module_name)
            raise
        finally:
            plugin_registry.clear()

    def _validate_names(
        self,
        plugin_name: str,
        tools: list[ToolMeta],
        jobs: list[JobSpec],
    ) -> None:
        """在发布前拒绝动态工具和后台任务名称冲突。"""

        tool_names = [item.name for item in tools]
        if len(tool_names) != len(set(tool_names)):
            raise ValueError(f"插件 {plugin_name} 存在重复工具名称")
        if self._tool_registry is not None:
            existing = self._tool_registry.list_tool_names()
            with self._lock:
                old = self._loaded.get(plugin_name)
            if old is not None:
                existing.difference_update(old.tool_names)
            conflicts = existing.intersection(tool_names)
            if conflicts:
                raise ValueError(f"插件工具名称冲突: {', '.join(sorted(conflicts))}")

        job_names = [item.name for item in jobs]
        if len(job_names) != len(set(job_names)):
            raise ValueError(f"插件 {plugin_name} 存在重复后台任务名称")

    async def _publish(self, candidate: _PreparedPlugin) -> None:
        """以候选贡献替换同名旧插件，并清理旧实例。"""

        name = candidate.name
        with self._lock:
            previous = self._loaded.get(name)
        subscribers = self._bind_handlers(candidate)
        hooks = self._build_hooks(candidate)
        tool_entries = self._build_tools(candidate)
        tools = [tool.name for tool, _ in tool_entries]
        replaced_tools = False
        if self._tool_registry is not None:
            previous_names = set(previous.tool_names) if previous is not None else set()
            if hasattr(self._tool_registry, "replace_many"):
                self._tool_registry.replace_many(previous_names, tool_entries)
                replaced_tools = True
            else:
                for tool, risk in tool_entries:
                    self._tool_registry.register_with_meta(
                        tool,
                        risk=risk,
                        source_type="plugin",
                        source_name=candidate.name,
                    )
        jobs = self._bind_jobs(candidate)
        self._tool_hook_executor.replace_plugin(name, hooks)
        active = _ActivePlugin(
            prepared=candidate,
            subscribers=subscribers,
            tool_names=tools,
            job_names=jobs,
        )
        with self._lock:
            self._loaded[name] = active
        if previous is not None:
            self._remove_bindings(
                previous,
                keep_tools=(
                    set(previous.tool_names) if replaced_tools else set(tools)
                ),
                keep_jobs=set(jobs),
            )
            try:
                await previous.prepared.instance.shutdown()
            except Exception:
                logger.exception("插件旧代关闭失败: %s", name)
            _discard_modules(previous.prepared.module_name)
        logger.info("插件代际已发布: %s revision=%s", name, candidate.revision[:12])

    async def _unload(self, name: str) -> None:
        """注销插件能力并关闭实例，但保留 plugin-data。"""

        with self._lock:
            active = self._loaded.pop(name, None)
        if active is None:
            return
        self._remove_bindings(active)
        self._tool_hook_executor.unregister_plugin(name)
        try:
            await active.prepared.instance.shutdown()
        except Exception:
            logger.exception("插件关闭失败: %s", name)
        _discard_modules(active.prepared.module_name)

    def _bind_handlers(self, candidate: _PreparedPlugin) -> list[Any]:
        subscribers: list[Any] = []
        if self._event_bus is None:
            return subscribers
        for meta in candidate.handlers:
            if meta.kind != MetadataKind.LIFECYCLE:
                continue
            subscriber = PluginEventSubscriber(
                functools.partial(meta.handler, candidate.instance),
                meta.event_type,
            )
            self._event_bus.subscribe(subscriber)
            subscribers.append(subscriber)
        return subscribers

    def _build_hooks(self, candidate: _PreparedPlugin) -> list[_PluginToolHook]:
        hooks: list[_PluginToolHook] = []
        for meta in candidate.handlers:
            if meta.kind != MetadataKind.TOOL_HOOK:
                continue
            hooks.append(_PluginToolHook(
                tool_name=meta.tool_name,
                priority=meta.priority,
                handler=functools.partial(meta.handler, candidate.instance),
                plugin_id=candidate.name,
            ))
        return hooks

    def _build_tools(
        self,
        candidate: _PreparedPlugin,
    ) -> list[tuple[DynamicPluginTool, str]]:
        if self._tool_registry is None:
            return []
        entries: list[tuple[DynamicPluginTool, str]] = []
        for meta in candidate.tools:
            tool = DynamicPluginTool(
                name=meta.name,
                description=meta.description,
                schema=meta.schema,
                execute_fn=functools.partial(meta.handler, candidate.instance),
            )
            entries.append((tool, "external-side-effect"))
        return entries

    def _bind_jobs(self, candidate: _PreparedPlugin) -> list[str]:
        if self._background_registry is None:
            return []
        names: list[str] = []
        for spec in candidate.background_jobs:
            qualified = f"{candidate.name}:{spec.name}"
            self._background_registry.register(JobSpec(
                name=qualified,
                func=spec.func,
                max_retries=spec.max_retries,
                interval_seconds=spec.interval_seconds,
                event_type=spec.event_type,
                debounce_seconds=spec.debounce_seconds,
                coalesce=spec.coalesce,
                retry_delay_seconds=spec.retry_delay_seconds,
                retry_backoff_factor=spec.retry_backoff_factor,
            ))
            names.append(qualified)
        return names

    def _remove_bindings(
        self,
        active: _ActivePlugin,
        *,
        keep_tools: set[str] | None = None,
        keep_jobs: set[str] | None = None,
    ) -> None:
        keep_tools = keep_tools or set()
        keep_jobs = keep_jobs or set()
        if self._event_bus is not None:
            for subscriber in active.subscribers:
                self._event_bus.unsubscribe(subscriber)
        if self._tool_registry is not None:
            for name in active.tool_names:
                if name not in keep_tools:
                    self._tool_registry.unregister(name)
        if self._background_registry is not None:
            for name in active.job_names:
                if name not in keep_jobs:
                    self._background_registry.unregister(name)

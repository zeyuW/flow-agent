"""插件工具前置钩子的上下文、结果与执行管线。"""

from dataclasses import dataclass, field
import asyncio
import threading
from typing import Any


@dataclass(slots=True)
class HookOutcome:
    """工具钩子处理结果。"""
    decision: str = "allow"  # allow、deny 或 modify
    reason: str = ""
    modified_args: dict[str, Any] | None = None


@dataclass(slots=True)
class PreToolCtx:
    """工具执行前传给 @on_tool_pre 的上下文。"""
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    session_key: str = ""


@dataclass(slots=True)
class _PluginToolHook:
    """插件工具钩子的宿主适配器。"""
    tool_name: str | None
    priority: int
    handler: Any  # 已绑定插件实例的方法
    plugin_id: str = ""

    async def run(self, ctx: PreToolCtx) -> HookOutcome | None:
        """执行钩子；None 表示放行，HookOutcome 表示阻止或修改。"""
        if self.tool_name and self.tool_name != ctx.tool_name:
            return None
        result = self.handler(ctx)
        # 同时支持同步和异步插件处理器
        if asyncio.iscoroutine(result):
            result = await result
        if result is None:
            return None
        if isinstance(result, HookOutcome):
            return result
        if isinstance(result, dict):
            return HookOutcome(decision="modify", modified_args=result)
        return None


class ToolHookExecutor:
    """按优先级执行当前代际的全部工具钩子。"""

    def __init__(self) -> None:
        self._hooks: list[_PluginToolHook] = []
        self._lock = threading.RLock()

    def register(self, hook: _PluginToolHook) -> None:
        with self._lock:
            self._hooks.append(hook)

    def replace_plugin(
        self,
        plugin_id: str,
        hooks: list[_PluginToolHook],
    ) -> None:
        """原子替换一个插件贡献的全部工具前置钩子。"""

        with self._lock:
            self._hooks = [hook for hook in self._hooks if hook.plugin_id != plugin_id]
            self._hooks.extend(hooks)

    def unregister_plugin(self, plugin_id: str) -> None:
        """移除一个插件贡献的全部工具钩子。"""

        self.replace_plugin(plugin_id, [])

    def unregister_all(self) -> None:
        with self._lock:
            self._hooks.clear()

    async def execute(self, tool_name: str, arguments: dict[str, Any], session_key: str = "") -> HookOutcome:
        """高优先级先执行；遇到 deny 立即停止，修改参数则继续传递。"""
        ctx = PreToolCtx(tool_name=tool_name, arguments=dict(arguments), session_key=session_key)
        modified: dict[str, Any] = dict(arguments)

        with self._lock:
            hooks = list(self._hooks)
        for hook in sorted(hooks, key=lambda h: -h.priority):
            result = await hook.run(ctx)
            if result is None:
                continue
            if result.decision == "deny":
                return result
            if result.decision == "modify" and result.modified_args:
                modified.update(result.modified_args)
                ctx.arguments = modified

        return HookOutcome(decision="allow", modified_args=modified)

    def execute_sync(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        session_key: str = "",
    ) -> HookOutcome:
        """在同步被动链路中执行可能为异步的插件钩子。"""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.execute(tool_name, arguments, session_key))

        result: list[HookOutcome] = []
        errors: list[BaseException] = []

        def run_in_thread() -> None:
            try:
                result.append(
                    asyncio.run(self.execute(tool_name, arguments, session_key))
                )
            except BaseException as exc:
                errors.append(exc)

        thread = threading.Thread(
            target=run_in_thread,
            name=f"plugin-tool-hook:{tool_name}",
        )
        thread.start()
        thread.join()
        if errors:
            raise errors[0]
        return result[0]

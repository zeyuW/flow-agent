"""Tool hook execution pipeline: PreToolCtx, HookOutcome, exec loop (spec 4c)."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class HookOutcome:
    """Return value from a tool hook handler."""
    decision: str = "allow"  # allow | deny | modify
    reason: str = ""
    modified_args: dict[str, Any] | None = None


@dataclass(slots=True)
class PreToolCtx:
    """Context passed to @on_tool_pre handlers before tool execution (spec 4c)."""
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    session_key: str = ""


@dataclass(slots=True)
class _PluginToolHook:
    """Adapter wrapping a plugin's tool hook handler."""
    tool_name: str | None
    priority: int
    handler: Any  # The bound plugin method

    async def run(self, ctx: PreToolCtx) -> HookOutcome | None:
        """Execute the hook handler. Returns None (pass), HookOutcome (block/modify) (spec 4c)."""
        if self.tool_name and self.tool_name != ctx.tool_name:
            return None
        result = self.handler(ctx)
        # Support both sync and async handlers
        import asyncio
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
    """Execute the tool hook pipeline against all registered hooks."""

    def __init__(self) -> None:
        self._hooks: list[_PluginToolHook] = []

    def register(self, hook: _PluginToolHook) -> None:
        self._hooks.append(hook)

    def unregister_all(self) -> None:
        self._hooks.clear()

    async def execute(self, tool_name: str, arguments: dict[str, Any], session_key: str = "") -> HookOutcome:
        """Run all hooks in priority order. Returns first deny outcome, or modified args, or allow.

        Order: higher priority runs first. If any hook returns deny, stop and return.
        If hook returns modified_args, update arguments and continue.
        """
        ctx = PreToolCtx(tool_name=tool_name, arguments=dict(arguments), session_key=session_key)
        modified: dict[str, Any] = dict(arguments)

        for hook in sorted(self._hooks, key=lambda h: -h.priority):
            result = await hook.run(ctx)
            if result is None:
                continue
            if result.decision == "deny":
                return result
            if result.decision == "modify" and result.modified_args:
                modified.update(result.modified_args)
                ctx.arguments = modified

        return HookOutcome(decision="allow", modified_args=modified)

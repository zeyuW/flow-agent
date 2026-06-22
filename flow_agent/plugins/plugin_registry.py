"""Global plugin registry with auto-registration via __init_subclass__ (spec 1c)."""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable


class MetadataKind(Enum):
    LIFECYCLE = auto()   # EventBus handler
    TOOL_HOOK = auto()   # @on_tool_pre
    TOOL = auto()        # @tool


class HandlerType(Enum):
    GATE = auto()  # Can modify/abort
    TAP = auto()   # Observe only


@dataclass(slots=True)
class HandlerMeta:
    kind: MetadataKind
    handler: Callable
    handler_type: HandlerType = HandlerType.TAP
    event_type: str = ""
    priority: int = 0
    tool_name: str | None = None  # For TOOL_HOOK


@dataclass(slots=True)
class ToolMeta:
    name: str
    handler: Callable
    description: str = ""
    schema: dict[str, Any] | None = None


@dataclass
class PluginRegistry:
    """Global registry for plugin classes and their handler metadata.

    Plugin classes are auto-registered via __init_subclass__.
    Decorators (@on_before_turn, @on_tool_pre, @tool) append metadata.
    """

    _classes: dict[str, type] = field(default_factory=dict)
    _handlers: list[HandlerMeta] = field(default_factory=list)
    _tools: list[ToolMeta] = field(default_factory=list)

    def register_class(self, cls: type) -> None:
        self._classes[cls.__name__] = cls

    def add_handler(self, meta: HandlerMeta) -> None:
        self._handlers.append(meta)

    def add_tool(self, meta: ToolMeta) -> None:
        self._tools.append(meta)

    def pop_class(self, name: str) -> type | None:
        return self._classes.pop(name, None)

    def pop_handlers(self) -> list[HandlerMeta]:
        handlers = list(self._handlers)
        self._handlers.clear()
        return handlers

    def pop_tools(self) -> list[ToolMeta]:
        tools = list(self._tools)
        self._tools.clear()
        return tools


# Global singleton
plugin_registry = PluginRegistry()

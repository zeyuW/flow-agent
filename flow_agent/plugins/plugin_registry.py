"""动态导入插件期间使用的临时元数据注册表。"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable


class MetadataKind(Enum):
    LIFECYCLE = auto()   # EventBus 生命周期处理器
    TOOL_HOOK = auto()   # @on_tool_pre 工具钩子
    TOOL = auto()        # @tool 动态工具


class HandlerType(Enum):
    GATE = auto()  # 可以修改或中止
    TAP = auto()   # 只观察


@dataclass(slots=True)
class HandlerMeta:
    kind: MetadataKind
    handler: Callable
    handler_type: HandlerType = HandlerType.TAP
    event_type: str = ""
    priority: int = 0
    tool_name: str | None = None  # 仅供 TOOL_HOOK 使用


@dataclass(slots=True)
class ToolMeta:
    name: str
    handler: Callable
    description: str = ""
    schema: dict[str, Any] | None = None


@dataclass
class PluginRegistry:
    """收集动态导入期间产生的插件类、处理器和工具元数据。"""

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

    def clear(self) -> None:
        """清除一次动态导入遗留的临时注册元数据。"""

        self._classes.clear()
        self._handlers.clear()
        self._tools.clear()


# 动态导入期间使用的进程级临时注册表
plugin_registry = PluginRegistry()

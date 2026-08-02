"""插件装饰器：@on_before_turn, @on_after_turn, @on_tool_pre, @tool。"""

import functools
import inspect
from typing import Any, Callable

from modules.capabilities.plugins.plugin_registry import (
    HandlerMeta,
    HandlerType,
    MetadataKind,
    ToolMeta,
    plugin_registry,
)


# ── EventBus 生命周期装饰器 ──

def on_before_turn(**options: Any):
    """GATE 处理器：可以中止回合。"""
    return _lifecycle_decorator("before_turn", HandlerType.GATE, **options)


def on_after_turn(**options: Any):
    """TAP 处理器：仅观察。"""
    return _lifecycle_decorator("after_turn", HandlerType.TAP, **options)


def on_turn_started(**options: Any):
    """回合开始时的 TAP 处理器。"""
    return _lifecycle_decorator("turn_started", HandlerType.TAP, **options)


def on_after_reasoning(**options: Any):
    """推理后的 TAP 处理器。"""
    return _lifecycle_decorator("after_reasoning", HandlerType.TAP, **options)


def _lifecycle_decorator(event_type: str, handler_type: HandlerType, **options: Any):
    def decorator(fn: Callable) -> Callable:
        priority = options.get("priority", 0)
        meta = HandlerMeta(
            kind=MetadataKind.LIFECYCLE,
            handler=fn,
            handler_type=handler_type,
            event_type=event_type,
            priority=priority,
        )
        plugin_registry.add_handler(meta)
        return fn
    return decorator


# ── 工具调用前钩子 ──

def on_tool_pre(*, tool_name: str | None = None, **options: Any):
    """在执行前拦截工具调用。返回 None 表示通过，返回 HookOutcome 表示阻止或修改。"""
    def decorator(fn: Callable) -> Callable:
        meta = HandlerMeta(
            kind=MetadataKind.TOOL_HOOK,
            handler=fn,
            handler_type=HandlerType.GATE,
            tool_name=tool_name,
            priority=options.get("priority", 0),
        )
        plugin_registry.add_handler(meta)
        return fn
    return decorator


# ── 工具注册 ──

def tool(**options: Any):
    """将方法注册为 LLM 可调用工具。模式从签名和文档字符串自动生成。"""
    def decorator(fn: Callable) -> Callable:
        name = options.get("name") or fn.__name__
        desc = options.get("description") or _doc_short(fn)
        schema = options.get("schema") or _build_schema(fn, desc)
        meta = ToolMeta(name=name, handler=fn, description=desc, schema=schema)
        plugin_registry.add_tool(meta)
        return fn
    return decorator


# ── 模式构建器 ──

_TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}

def _build_schema(fn: Callable, desc: str) -> dict:
    sig = inspect.signature(fn)
    props: dict[str, Any] = {}
    required: list[str] = []

    for pname, param in sig.parameters.items():
        if pname in ("self", "cls"):
            continue
        ptype = _TYPE_MAP.get(param.annotation, "string")
        pdesc = _param_desc(fn, pname)
        props[pname] = {"type": ptype, "description": pdesc}
        if param.default is inspect.Parameter.empty:
            required.append(pname)

    return {
        "type": "object",
        "properties": props,
        "required": required,
    }


def _doc_short(fn: Callable) -> str:
    doc = (inspect.getdoc(fn) or "").strip()
    return doc.split("\n")[0][:120] if doc else ""


def _param_desc(fn: Callable, pname: str) -> str:
    """Extract param description from Args: section of docstring."""
    doc = inspect.getdoc(fn) or ""
    in_args = False
    for line in doc.splitlines():
        s = line.strip()
        if s.lower().startswith("args:"):
            in_args = True
            continue
        if in_args:
            if s.startswith(pname):
                parts = s.split(":", 1)
                return parts[1].strip() if len(parts) > 1 else ""
            if s and not s.startswith(" ") and not s.startswith("\t"):
                break
    return ""

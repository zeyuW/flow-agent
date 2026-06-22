"""Plugin decorators: @on_before_turn, @on_after_turn, @on_tool_pre, @tool (spec 3,4,5)."""

import functools
import inspect
from typing import Any, Callable

from flow_agent.plugins.plugin_registry import (
    HandlerMeta,
    HandlerType,
    MetadataKind,
    ToolMeta,
    plugin_registry,
)


# ── EventBus lifecycle decorators (spec 3a-3b) ──

def on_before_turn(**options: Any):
    """GATE handler: can abort the turn (spec 3a)."""
    return _lifecycle_decorator("before_turn", HandlerType.GATE, **options)


def on_after_turn(**options: Any):
    """TAP handler: observe only (spec 3a)."""
    return _lifecycle_decorator("after_turn", HandlerType.TAP, **options)


def on_turn_started(**options: Any):
    """TAP handler for turn started."""
    return _lifecycle_decorator("turn_started", HandlerType.TAP, **options)


def on_after_reasoning(**options: Any):
    """TAP handler for after reasoning."""
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


# ── Tool pre-call hook (spec 4a) ──

def on_tool_pre(*, tool_name: str | None = None, **options: Any):
    """Intercept tool calls before execution. Return None to pass, HookOutcome to block/modify (spec 4a)."""
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


# ── Tool registration (spec 5a-5b) ──

def tool(**options: Any):
    """Register a method as an LLM-callable tool. Schema auto-generated from signature + docstring."""
    def decorator(fn: Callable) -> Callable:
        name = options.get("name") or fn.__name__
        desc = options.get("description") or _doc_short(fn)
        schema = options.get("schema") or _build_schema(fn, desc)
        meta = ToolMeta(name=name, handler=fn, description=desc, schema=schema)
        plugin_registry.add_tool(meta)
        return fn
    return decorator


# ── Schema builder (spec 5b) ──

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

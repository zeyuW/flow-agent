"""工具协议与注册能力。"""

from application.capabilities.tools.base import Tool, ToolResult
from application.capabilities.tools.registry import ToolRegistry
from application.capabilities.tools.guard import ToolGuard

__all__ = ["Tool", "ToolGuard", "ToolRegistry", "ToolResult"]

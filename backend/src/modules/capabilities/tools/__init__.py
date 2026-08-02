"""工具协议与注册能力。"""

from modules.capabilities.tools.base import Tool, ToolResult
from modules.capabilities.tools.registry import ToolRegistry
from modules.capabilities.tools.guard import ToolGuard

__all__ = ["Tool", "ToolGuard", "ToolRegistry", "ToolResult"]

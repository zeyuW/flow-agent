"""MCP 内置服务的旧路径转发层。"""

import sys

from modules.capabilities.mcp import builtin_server as _implementation

sys.modules[__name__] = _implementation

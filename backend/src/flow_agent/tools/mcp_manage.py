"""只读 MCP 状态查询工具。"""

import json
import logging
from dataclasses import dataclass
from typing import Any

from modules.capabilities.mcp.server_registry import McpServerRegistry
from flow_agent.tools.base import ToolResult

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class McpListTool:
    """列出统一用户配置和插件声明产生的 MCP 服务。"""

    registry: McpServerRegistry

    @property
    def name(self) -> str:
        return "mcp_list"

    @property
    def description(self) -> str:
        return "列出当前已连接的 MCP 服务、工具以及用户配置文件路径"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def run(self, tool_input: dict[str, str]) -> ToolResult:
        del tool_input
        try:
            payload = {
                "config_path": str(self.registry.config_path),
                "servers": self.registry.list_servers(),
            }
            return ToolResult(
                ok=True,
                content=json.dumps(payload, ensure_ascii=False, indent=2),
            )
        except Exception as exc:
            logger.exception("MCP 状态读取失败")
            return ToolResult(ok=False, content=f"MCP 状态读取失败: {exc}")

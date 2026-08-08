"""MCP 工具包装器：将 MCP 远端工具适配为内部 Tool 协议。

McpToolWrapper.execute() 把内部同步工具调用转发到常驻 MCP 客户端。
"""

import logging
from dataclasses import dataclass
from typing import Any

from application.capabilities.mcp.mcp_client import McpClient, McpToolInfo
from application.capabilities.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class McpToolWrapper:
    """将 MCP 工具包装为内部 Tool 协议（spec 2f）。

    工具名格式：mcp__{server_name}__{tool_name}，避免与内置工具冲突。
    调用时通过客户端锁保证同一服务的 JSON-RPC 请求顺序一致。
    """

    client: McpClient
    info: McpToolInfo
    server_name: str = ""

    @property
    def name(self) -> str:
        """工具名：mcp__{server}__{tool}（spec 2f 格式）。"""
        srv = self.server_name or self.client.name
        return f"mcp__{srv}__{self.info.name}"

    @property
    def description(self) -> str:
        base = self.info.description or f"MCP tool from {self.client.name}"
        return f"[MCP:{self.client.name}] {base}"

    @property
    def input_schema(self) -> dict[str, Any]:
        """返回工具的 JSON Schema（从 MCP server 的 inputSchema 获取）。"""
        if self.info.input_schema:
            return self.info.input_schema
        # 服务未提供输入约束时使用开放对象结构。
        return {
            "type": "object",
            "additionalProperties": True,
        }

    # ── 工具协议实现 ──

    def run(self, tool_input: dict[str, str]) -> ToolResult:
        """同步执行 MCP 工具调用。"""
        try:
            result_text = self.client.call_sync(
                tool_name=self.info.name,
                arguments=tool_input,
            )
            return ToolResult(ok=True, content=result_text)
        except TimeoutError as exc:
            logger.error("MCP tool timeout: %s/%s", self.client.name, self.info.name)
            return ToolResult(ok=False, content=f"MCP timeout: {exc}")
        except ConnectionError as exc:
            logger.error("MCP connection lost: %s/%s", self.client.name, self.info.name)
            return ToolResult(ok=False, content=f"MCP connection lost: {exc}")
        except Exception as exc:
            logger.exception("MCP tool error: %s/%s", self.client.name, self.info.name)
            return ToolResult(ok=False, content=f"MCP tool error: {exc}")

    def execute(self, **kwargs: Any) -> str:
        """便捷执行方法：返回纯文本结果。

        Args:
            **kwargs: 工具参数。

        Returns:
            工具执行结果文本。
        """
        result = self.run(kwargs)
        return result.content

    def to_openai_function(self) -> dict[str, Any]:
        """导出为 OpenAI function 格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

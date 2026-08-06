from dataclasses import dataclass

from application.capabilities.mcp.registry import MCPRegistry
from application.capabilities.tools.base import ToolResult


@dataclass(slots=True)
class MCPToolAdapter:
    """Adapt one MCP tool into internal Tool protocol."""

    server_name: str
    tool_name: str
    description_text: str
    registry: MCPRegistry

    @property
    def name(self) -> str:
        return f"mcp:{self.server_name}:{self.tool_name}"

    @property
    def description(self) -> str:
        return self.description_text

    @property
    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "additionalProperties": True,
        }

    def run(self, tool_input: dict[str, str]) -> ToolResult:
        try:
            result = self.registry.call_tool(self.server_name, self.tool_name, tool_input)
            return ToolResult(ok=True, content=result)
        except Exception as exc:
            return ToolResult(ok=False, content=f"mcp tool error: {exc}")


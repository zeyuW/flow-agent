from dataclasses import dataclass
from typing import Callable


@dataclass(slots=True)
class MCPToolInfo:
    """Basic metadata for an MCP exposed tool."""

    name: str
    description: str


class MCPClient:
    """Minimal in-process MCP client abstraction for external tool providers."""

    def __init__(
        self,
        server_name: str,
        tool_handlers: dict[str, Callable[[dict[str, str]], str]] | None = None,
    ) -> None:
        self.server_name = server_name
        self._tool_handlers = tool_handlers or {}
        self._mounted = False

    def mount(self) -> None:
        self._mounted = True

    def unmount(self) -> None:
        self._mounted = False

    @property
    def is_mounted(self) -> bool:
        return self._mounted

    def discover_tools(self) -> list[MCPToolInfo]:
        if not self._mounted:
            return []
        return [
            MCPToolInfo(
                name=name,
                description=f"Tool from MCP server {self.server_name}",
            )
            for name in self._tool_handlers
        ]

    def call_tool(self, tool_name: str, tool_input: dict[str, str]) -> str:
        if not self._mounted:
            raise RuntimeError(f"MCP server not mounted: {self.server_name}")
        handler = self._tool_handlers.get(tool_name)
        if handler is None:
            raise ValueError(f"Unknown MCP tool {tool_name} on {self.server_name}")
        return handler(tool_input)


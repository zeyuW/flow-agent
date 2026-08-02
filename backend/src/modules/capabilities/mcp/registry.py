from dataclasses import dataclass, field

from modules.capabilities.mcp.client import MCPClient


@dataclass(slots=True)
class MCPServerConfig:
    """Configuration entry for an external MCP server."""

    name: str
    enabled: bool = True
    tools: list[str] = field(default_factory=list)


class MCPRegistry:
    """Register, mount, and route mounted MCP servers."""

    def __init__(self) -> None:
        self._configs: dict[str, MCPServerConfig] = {}
        self._clients: dict[str, MCPClient] = {}

    def register_server(self, config: MCPServerConfig, client: MCPClient) -> None:
        self._configs[config.name] = config
        self._clients[config.name] = client

    def mount(self, server_name: str) -> None:
        client = self._clients[server_name]
        client.mount()

    def unmount(self, server_name: str) -> None:
        client = self._clients[server_name]
        client.unmount()

    def mounted_servers(self) -> list[str]:
        return [
            name
            for name, client in self._clients.items()
            if self._configs.get(name, MCPServerConfig(name=name)).enabled and client.is_mounted
        ]

    def discover_tools(self) -> list[tuple[str, str, str]]:
        rows: list[tuple[str, str, str]] = []
        for server_name in self.mounted_servers():
            for tool in self._clients[server_name].discover_tools():
                rows.append((server_name, tool.name, tool.description))
        return rows

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        tool_input: dict[str, str],
    ) -> str:
        return self._clients[server_name].call_tool(tool_name, tool_input)


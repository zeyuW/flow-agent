from dataclasses import dataclass

from flow_agent.mcp.registry import MCPRegistry


@dataclass(slots=True)
class ProviderFacade:
    mcp_registry: MCPRegistry

    def mounted(self) -> list[str]:
        return self.mcp_registry.mounted_servers()

    def discover_tools(self) -> list[tuple[str, str, str]]:
        return self.mcp_registry.discover_tools()

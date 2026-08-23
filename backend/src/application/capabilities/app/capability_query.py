"""管理端使用的能力只读查询。"""

from typing import Any

from application.capabilities.mcp.server_registry import McpServerRegistry
from application.capabilities.skills.catalog import SkillCatalog


class CapabilityQueryService:
    """组合普通 Skill 目录与 MCP 连接运行状态。"""

    def __init__(self, catalog: SkillCatalog, mcp_registry: McpServerRegistry) -> None:
        self._catalog = catalog
        self._mcp_registry = mcp_registry

    def get_capabilities(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "skills": [
                {
                    "name": item.name,
                    "description": item.description,
                    "source": item.source,
                    "status": item.status,
                    "reason": item.reason,
                }
                for item in self._catalog.list_items()
            ],
            "connectors": [
                {
                    "name": server["name"],
                    "enabled": server["enabled"],
                    "connected": server["connected"],
                    "tools": server["tools"],
                }
                for server in self._mcp_registry.list_configured_servers()
            ],
        }

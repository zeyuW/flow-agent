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
        skills = self._catalog.list_items()
        return {
            "skills": [
                {
                    "name": item.name,
                    "description": item.description,
                    "source": item.source,
                    "status": item.status,
                    "reason": item.reason,
                }
                for item in skills
            ],
            "connectors": [
                {
                    "name": server["name"],
                    "enabled": server["enabled"],
                    "connected": server["connected"],
                    "tools": server["tools"],
                    "description": server.get("description") or "为 Agent 提供外部工具能力。",
                    "transport": server.get("transport"),
                    "protocol_version": server.get("protocol_version"),
                    "error": server.get("error"),
                    "related_skills": [
                        item.name
                        for item in skills
                        if server["name"] in item.spec.requires_mcp
                    ],
                }
                for server in self._mcp_registry.list_configured_servers()
            ],
        }

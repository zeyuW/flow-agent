"""宿主内置 MCP 服务目录。"""

from __future__ import annotations

import sys
from pathlib import Path

from modules.capabilities.mcp.config import McpServerSpec


def builtin_mcp_catalog() -> dict[str, McpServerSpec]:
    """返回默认随 Agent 发布的基础 MCP 服务。"""
    project_root = Path(__file__).resolve().parents[3]
    server_file = Path(__file__).with_name("builtin_server.py")
    return {
        name: McpServerSpec(
            name=name,
            command=(
                sys.executable,
                "-m",
                "modules.capabilities.mcp.builtin_server",
                "--profile",
                name,
            ),
            cwd=str(project_root),
            watch_paths=(str(server_file),),
            source=f"builtin:{name}",
        )
        for name in ("weather", "ai-news")
    }

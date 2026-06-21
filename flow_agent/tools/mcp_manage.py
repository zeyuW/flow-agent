"""MCP 管理工具：mcp_add / mcp_remove / mcp_list。

实现 spec 1b：三个工具注册到 ToolRegistry，让 LLM 可以在运行时动态管理 MCP servers。
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from flow_agent.mcp.server_registry import McpServerRegistry
from flow_agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


def _run_async(coro):
    """同步桥接 async 协程。"""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=120)
        return loop.run_until_complete(coro)


@dataclass(slots=True)
class McpAddTool:
    """mcp_add 工具：添加并连接一个 MCP server（spec 2a）。"""

    registry: McpServerRegistry

    @property
    def name(self) -> str:
        return "mcp_add"

    @property
    def description(self) -> str:
        return (
            "添加一个 MCP (Model Context Protocol) server。"
            "参数: name (server 名称), command (启动命令数组), "
            "env (可选, 环境变量), cwd (可选, 工作目录)"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "MCP server 的名称，用于标识和管理",
                },
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "启动 MCP server 的命令，如 ['python', 'server.py']",
                },
                "env": {
                    "type": "object",
                    "description": "可选的环境变量",
                },
                "cwd": {
                    "type": "string",
                    "description": "可选的工作目录",
                },
            },
            "required": ["name", "command"],
        }

    def run(self, tool_input: dict[str, str]) -> ToolResult:
        try:
            name = tool_input.get("name", "")
            command_raw = tool_input.get("command", [])
            if isinstance(command_raw, str):
                import shlex
                command = shlex.split(command_raw)
            else:
                command = list(command_raw)

            env_raw = tool_input.get("env")
            env = dict(env_raw) if env_raw else None
            cwd = tool_input.get("cwd")

            result = _run_async(
                self.registry.add(name=name, command=command, env=env, cwd=cwd)
            )
            return ToolResult(ok=True, content=result)
        except Exception as exc:
            logger.exception("mcp_add failed")
            return ToolResult(ok=False, content=f"mcp_add 失败: {exc}")


@dataclass(slots=True)
class McpRemoveTool:
    """mcp_remove 工具：移除一个 MCP server 并清理资源（spec 4c）。"""

    registry: McpServerRegistry

    @property
    def name(self) -> str:
        return "mcp_remove"

    @property
    def description(self) -> str:
        return (
            "移除一个已连接的 MCP server 并清理其所有工具。"
            "参数: name (要移除的 server 名称)"
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "要移除的 MCP server 名称",
                },
            },
            "required": ["name"],
        }

    def run(self, tool_input: dict[str, str]) -> ToolResult:
        try:
            name = tool_input.get("name", "")
            result = _run_async(self.registry.remove(name))
            return ToolResult(ok=True, content=result)
        except Exception as exc:
            logger.exception("mcp_remove failed")
            return ToolResult(ok=False, content=f"mcp_remove 失败: {exc}")


@dataclass(slots=True)
class McpListTool:
    """mcp_list 工具：列出所有已注册的 MCP servers 及其工具。"""

    registry: McpServerRegistry

    @property
    def name(self) -> str:
        return "mcp_list"

    @property
    def description(self) -> str:
        return "列出所有已注册的 MCP servers 及其提供的工具"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
        }

    def run(self, tool_input: dict[str, str]) -> ToolResult:
        try:
            servers = self.registry.list_servers()
            if not servers:
                return ToolResult(ok=True, content="当前无已注册的 MCP servers")
            result = json.dumps(servers, ensure_ascii=False, indent=2)
            return ToolResult(ok=True, content=result)
        except Exception as exc:
            logger.exception("mcp_list failed")
            return ToolResult(ok=False, content=f"mcp_list 失败: {exc}")

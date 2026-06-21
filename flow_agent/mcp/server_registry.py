"""MCP 服务器注册表：管理多个 MCP server 的生命周期和工具注册。

实现 spec 1a-1d 和 4a-4d：
- 1a: McpServerRegistry 实例，持久化到 mcp_servers.json
- 1c: start_connect_all_background() 后台重连
- 1d: asyncio.gather 并行重连
- 4a: _save() 保存配置到文件
- 4b: _load_raw_configs() 从文件加载
- 4c: remove() 清理工具并断开连接
- 4d: disconnect() 优雅终止
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flow_agent.mcp.mcp_client import McpClient, McpToolInfo
from flow_agent.mcp.tool_wrapper import McpToolWrapper

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class McpServerRegistry:
    """MCP 服务器注册表：管理 MCP server 的生命周期。

    特性：
    - 持久化配置到 mcp_servers.json
    - 后台重连已配置的 servers
    - 工具注册/注销到 ToolRegistry
    - 并行连接多个 servers
    """

    config_path: Path
    tool_registry: Any  # ToolRegistry，避免循环导入
    _clients: dict[str, McpClient] = field(default_factory=dict)
    _server_tools: dict[str, list[str]] = field(default_factory=dict)
    _connect_task: asyncio.Task | None = None

    # ── 配置持久化 (spec 4a-4b) ──

    def _save(self) -> None:
        """保存所有 MCP server 配置到 mcp_servers.json（spec 4a）。"""
        servers = {
            name: {
                "command": client.command,
                "env": client.env,
                "cwd": client.cwd,
            }
            for name, client in self._clients.items()
        }
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(
                json.dumps({"servers": servers}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.debug("MCP config saved: %d servers", len(servers))
        except Exception:
            logger.exception("failed to save MCP config")

    def _load_raw_configs(self) -> dict[str, Any]:
        """从 mcp_servers.json 加载已配置的 servers（spec 4b）。"""
        if not self.config_path.exists():
            return {}
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            return data.get("servers", {})
        except (json.JSONDecodeError, OSError):
            logger.exception("failed to load MCP config")
            return {}

    # ── 后台重连 (spec 1c-1d) ──

    def start_connect_all_background(self) -> None:
        """后台重连所有已配置的 MCP servers（spec 1c）。

        不阻塞主服务启动，在后台通过 asyncio.create_task 执行。
        """
        if self._connect_task is None or self._connect_task.done():
            self._connect_task = asyncio.create_task(
                self.load_and_connect_all(),
                name="mcp_connect_all",
            )
            logger.info("MCP background reconnect started")

    async def load_and_connect_all(self) -> None:
        """从配置文件加载所有 servers 并并行连接（spec 1d）。"""
        configs = self._load_raw_configs()
        if not configs:
            logger.debug("MCP: no saved servers to reconnect")
            return

        logger.info("MCP: reconnecting %d saved servers", len(configs))

        async def connect_one(name: str, cfg: dict) -> None:
            try:
                client = McpClient(
                    name=name,
                    command=cfg.get("command", []),
                    env=cfg.get("env"),
                    cwd=cfg.get("cwd"),
                )
                tool_infos = await client.connect()
                self._clients[name] = client
                self._register_tools(name, client, tool_infos)
                logger.info("MCP reconnected: %s (%d tools)", name, len(tool_infos))
            except Exception:
                logger.exception("MCP reconnect failed: %s", name)

        await asyncio.gather(
            *(
                connect_one(name, cfg)
                for name, cfg in configs.items()
            )
        )
        self._save()

    # ── 添加 server (spec 2a) ──

    async def add(
        self,
        name: str,
        command: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> str:
        """添加并连接 MCP server（spec 2a）。

        检查重复 → 创建 McpClient → connect → 注册工具 → 保存配置。
        """
        if name in self._clients:
            return f"MCP server {name!r} 已存在。如需更新，请先移除再重新添加。"

        try:
            tool_infos = await self._connect(
                name=name,
                command=command,
                env=env,
                cwd=cwd,
            )
        except Exception as exc:
            logger.exception("MCP add failed: %s", name)
            return f"添加 MCP server {name!r} 失败: {exc}"

        self._save()
        return f"MCP server {name!r} 已添加，发现 {len(tool_infos)} 个工具"

    async def _connect(
        self,
        name: str,
        command: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> list[McpToolInfo]:
        """创建 McpClient 并连接（spec 2b）。"""
        client = McpClient(name=name, command=command, env=env, cwd=cwd)
        tool_infos = await client.connect()
        self._clients[name] = client
        self._register_tools(name, client, tool_infos)
        logger.info("MCP server added: %s (%d tools)", name, len(tool_infos))
        return tool_infos

    def _register_tools(
        self,
        server_name: str,
        client: McpClient,
        tool_infos: list[McpToolInfo],
    ) -> list[str]:
        """将 MCP 工具包装并注册到 ToolRegistry（spec 2f）。"""
        tool_names: list[str] = []
        for info in tool_infos:
            wrapper = McpToolWrapper(client=client, info=info, server_name=server_name)
            # 检查 ToolRegistry 是否有 register_with_meta 方法
            if hasattr(self.tool_registry, 'register_with_meta'):
                self.tool_registry.register_with_meta(
                    wrapper,
                    risk="external-side-effect",
                    source_type="mcp",
                    source_name=server_name,
                )
            else:
                self.tool_registry.register(wrapper)
            tool_names.append(wrapper.name)
        self._server_tools[server_name] = tool_names
        return tool_names

    # ── 移除 server (spec 4c-4d) ──

    async def remove(self, name: str) -> str:
        """移除 MCP server 并清理资源（spec 4c）。

        1. 注销该 server 提供的所有工具
        2. 断开子进程连接（spec 4d）
        3. 更新持久化配置
        """
        if name not in self._clients:
            existing = list(self._clients.keys()) or "无"
            return f"MCP server {name!r} 不存在，当前已注册：{existing}"

        # 注销工具
        for tool_name in self._server_tools.pop(name, []):
            if hasattr(self.tool_registry, 'unregister'):
                self.tool_registry.unregister(tool_name)
            elif hasattr(self.tool_registry, '_tools'):
                self.tool_registry._tools.pop(tool_name, None)

        # 断开连接（spec 4d）
        client = self._clients.pop(name)
        await client.disconnect()

        self._save()
        logger.info("MCP server removed: %s", name)
        return f"MCP server {name!r} 已移除"

    # ── 查询 ──

    def list_servers(self) -> list[dict[str, Any]]:
        """列出所有已注册的 MCP servers。"""
        result: list[dict[str, Any]] = []
        for name, client in self._clients.items():
            result.append({
                "name": name,
                "connected": client.is_connected,
                "command": client.command,
                "tools": self._server_tools.get(name, []),
            })
        return result

    @property
    def server_names(self) -> list[str]:
        return list(self._clients.keys())


def _run_async(coro):
    """从同步上下文运行异步协程的辅助函数。"""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        # 如果在已有事件循环中，创建新任务
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro)

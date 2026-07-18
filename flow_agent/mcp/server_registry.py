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
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flow_agent.mcp.config import McpServerSpec, load_workspace_mcp_specs, merge_mcp_specs
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
    startup_timeout: float = 30.0
    call_timeout: float = 60.0
    _clients: dict[str, McpClient] = field(default_factory=dict)
    _server_tools: dict[str, list[str]] = field(default_factory=dict)
    _connect_task: asyncio.Task | None = None
    _additional_specs: list[McpServerSpec] = field(default_factory=list)
    _watch_thread: threading.Thread | None = None
    _watch_stop: threading.Event = field(default_factory=threading.Event)
    _generation_lock: threading.RLock = field(default_factory=threading.RLock)
    _revision: str = ""

    def start(self, additional_specs: list[McpServerSpec] | None = None) -> None:
        """加载工作区和插件声明，并原子发布一代 MCP 工具。"""
        self._additional_specs = list(additional_specs or [])
        self.reload()
        self._start_watcher()

    def reload(self) -> None:
        """重新读取工作区声明；失败时保留当前可用连接。"""
        with self._generation_lock:
            specs = merge_mcp_specs(
                load_workspace_mcp_specs(self.config_path.parent),
                self._additional_specs,
            )
            revision = _specs_revision(specs)
            if (
                revision == self._revision
                and all(client.is_connected for client in self._clients.values())
            ):
                return
            self._replace_generation(specs)
            self._revision = revision

    def stop_all(self) -> None:
        """注销全部 MCP 工具并关闭所有服务进程。"""
        logger.debug("MCP registry stopping watcher")
        self._watch_stop.set()
        if self._watch_thread is not None:
            self._watch_thread.join(timeout=3.0)
            self._watch_thread = None
        logger.debug("MCP registry stopping clients")
        with self._generation_lock:
            clients = list(self._clients.values())
            for tool_names in self._server_tools.values():
                for tool_name in tool_names:
                    self.tool_registry.unregister(tool_name)
            self._server_tools.clear()
            self._clients.clear()
            self._revision = ""
            for client in clients:
                logger.debug("MCP registry stopping client: %s", client.name)
                client.stop()
        logger.debug("MCP registry stopped")

    def _start_watcher(self) -> None:
        """监视声明和 watch_paths，变化时尝试发布新代。"""
        if self._watch_thread is not None and self._watch_thread.is_alive():
            return
        self._watch_stop.clear()

        def watch() -> None:
            while not self._watch_stop.wait(1.0):
                try:
                    self.reload()
                except Exception:
                    logger.exception("MCP 热重载失败，继续使用上一代")

        self._watch_thread = threading.Thread(
            target=watch,
            name="mcp-config-watcher",
            daemon=True,
        )
        self._watch_thread.start()

    def _replace_generation(self, specs: list[McpServerSpec]) -> None:
        """先预热全部候选服务，成功后再替换旧代。"""
        candidates: dict[str, McpClient] = {}
        candidate_tools: dict[str, list[McpToolInfo]] = {}
        try:
            for spec in specs:
                client = McpClient(
                    name=spec.name,
                    command=list(spec.command),
                    env=spec.env or None,
                    cwd=spec.cwd,
                    call_timeout=self.call_timeout,
                )
                candidates[spec.name] = client
                candidate_tools[spec.name] = client.start(self.startup_timeout)
        except Exception:
            for client in candidates.values():
                client.stop()
            raise

        old_clients = self._clients
        old_tools = self._server_tools
        for tool_names in old_tools.values():
            for tool_name in tool_names:
                self.tool_registry.unregister(tool_name)

        self._clients = candidates
        self._server_tools = {}
        for name, client in candidates.items():
            self._register_tools(name, client, candidate_tools[name])
        for client in old_clients.values():
            client.stop()
        logger.info("MCP generation published: servers=%d", len(candidates))

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
        """兼容异步启动入口，实际连接由专用线程持有。"""
        await asyncio.to_thread(self.start)

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
        client = McpClient(
            name=name,
            command=command,
            env=env,
            cwd=cwd,
            call_timeout=self.call_timeout,
        )
        tool_infos = await asyncio.to_thread(client.start, self.startup_timeout)
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
        await asyncio.to_thread(client.stop)

        self._save()
        logger.info("MCP server removed: %s", name)
        return f"MCP server {name!r} 已移除"

    # ── 查询 ──

    def list_servers(self) -> list[dict[str, Any]]:
        """列出所有已注册的 MCP servers。"""
        with self._generation_lock:
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
        with self._generation_lock:
            return list(self._clients.keys())

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """通过统一注册表调用指定服务的工具。"""
        with self._generation_lock:
            client = self._clients.get(server_name)
            if client is None:
                raise KeyError(f"未知 MCP 服务: {server_name}")
            return client.call_sync(tool_name, arguments, timeout=self.call_timeout)


def _run_async(coro):
    """从同步上下文运行异步协程的辅助函数。"""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        # 如果在已有事件循环中，创建新任务
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro)


def _specs_revision(specs: list[McpServerSpec]) -> str:
    """汇总一代 MCP 声明及监视路径的修订值。"""
    import hashlib

    digest = hashlib.sha256()
    for spec in sorted(specs, key=lambda item: item.name):
        digest.update(spec.revision().encode())
    return digest.hexdigest()

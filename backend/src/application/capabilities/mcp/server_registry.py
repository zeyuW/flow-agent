"""统一用户配置和插件声明的 MCP 生命周期注册表。"""

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from application.capabilities.mcp.config import (
    McpServerSpec,
    load_mcp_config,
    load_project_mcp_specs,
    merge_mcp_specs,
    remove_mcp_server,
    save_mcp_server,
    set_mcp_server_enabled,
)
from application.capabilities.mcp.mcp_client import McpClient
from application.capabilities.mcp.http_client import McpHttpClient
from application.capabilities.mcp.tool_wrapper import McpToolWrapper

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class McpServerRegistry:
    """MCP 服务器注册表：管理 MCP server 的生命周期。

    特性：
    - 读取 ~/.flow/mcp.json 中的用户外部 MCP
    - 合并插件声明
    - 工具注册/注销到 ToolRegistry
    - 并行连接多个 servers
    """

    config_path: Path
    tool_registry: Any  # ToolRegistry，避免循环导入
    builtin_catalog: dict[str, McpServerSpec] = field(default_factory=dict)
    startup_timeout: float = 30.0
    call_timeout: float = 60.0
    _clients: dict[str, Any] = field(default_factory=dict)
    _server_tools: dict[str, list[str]] = field(default_factory=dict)
    _additional_specs: list[McpServerSpec] = field(default_factory=list)
    _server_errors: dict[str, str] = field(default_factory=dict)
    _server_descriptions: dict[str, str] = field(default_factory=dict)
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
                list(self.builtin_catalog.values()),
                load_project_mcp_specs(self.config_path),
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

    def update_additional_specs(self, specs: list[McpServerSpec]) -> None:
        """更新插件贡献的 MCP 声明，并尝试原子发布新代。"""

        with self._generation_lock:
            previous = self._additional_specs
            self._additional_specs = list(specs)
            try:
                self.reload()
            except Exception:
                self._additional_specs = previous
                raise

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
            tool_names = {
                tool_name
                for names in self._server_tools.values()
                for tool_name in names
            }
            if hasattr(self.tool_registry, "replace_many"):
                self.tool_registry.replace_many(tool_names, [])
            else:
                for tool_name in tool_names:
                    self.tool_registry.unregister(tool_name)
            self._server_tools.clear()
            self._clients.clear()
            self._server_errors.clear()
            self._server_descriptions.clear()
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
        candidate_tools: dict[str, list[Any]] = {}
        try:
            for spec in specs:
                if spec.url:
                    client = McpHttpClient(
                        name=spec.name,
                        url=spec.url,
                        headers=spec.headers,
                        call_timeout=self.call_timeout,
                    )
                else:
                    client = McpClient(
                        name=spec.name,
                        command=list(spec.command),
                        env=spec.env or None,
                        cwd=spec.cwd,
                        call_timeout=self.call_timeout,
                    )
                candidates[spec.name] = client
                candidate_tools[spec.name] = client.start(self.startup_timeout)
        except Exception as exc:
            if spec.name:
                self._server_errors[spec.name] = str(exc)
            for client in candidates.values():
                client.stop()
            raise

        self._server_errors.clear()
        self._server_descriptions = {
            spec.name: spec.description for spec in specs
        }

        old_clients = self._clients
        old_tools = self._server_tools
        old_tool_names = {
            tool_name
            for names in old_tools.values()
            for tool_name in names
        }
        new_server_tools: dict[str, list[str]] = {}
        additions: list[tuple[McpToolWrapper, str]] = []
        for name, client in candidates.items():
            wrappers = [
                McpToolWrapper(client=client, info=info, server_name=name)
                for info in candidate_tools[name]
            ]
            new_server_tools[name] = [wrapper.name for wrapper in wrappers]
            additions.extend(
                (wrapper, "external-side-effect") for wrapper in wrappers
            )
        if hasattr(self.tool_registry, "replace_many"):
            self.tool_registry.replace_many(old_tool_names, additions)
        else:
            for tool_name in old_tool_names:
                self.tool_registry.unregister(tool_name)
            for wrapper, _ in additions:
                self.tool_registry.register(wrapper)

        self._clients = candidates
        self._server_tools = new_server_tools
        for client in old_clients.values():
            client.stop()
        logger.info("MCP generation published: servers=%d", len(candidates))

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
                    "transport": "http" if isinstance(client, McpHttpClient) else "stdio",
                    "protocol_version": getattr(client, "protocol_version", None),
                    "error": self._server_errors.get(name),
                    "description": self._server_descriptions.get(name, ""),
                })
            return result

    def list_configured_servers(self) -> list[dict[str, Any]]:
        """列出用户配置中的 server，包括已禁用但未连接的服务。"""
        raw = load_mcp_config(self.config_path)
        connected = {item["name"]: item for item in self.list_servers()}
        result = []
        for name, value in raw["mcpServers"].items():
            item = connected.get(name, {})
            result.append({
                "name": name,
                "enabled": bool(value.get("enabled", True)),
                "connected": bool(item.get("connected", False)),
                "tools": item.get("tools", []),
                "transport": item.get("transport", "http" if value.get("url") else "stdio"),
                "protocol_version": item.get("protocol_version"),
                "error": item.get("error") or self._server_errors.get(name),
                "description": (
                    str(value.get("description", "")).strip()
                    or item.get("description")
                    or _default_description(name, item.get("tools", []))
                ),
                "command": str(value.get("command", "")),
                "url": value.get("url"),
                "args": value.get("args", []),
                "cwd": value.get("cwd"),
                "env": value.get("env", {}),
                "headers": value.get("headers", {}),
            })
        configured_names = set(raw["mcpServers"])
        for item in connected.values():
            if item["name"] not in configured_names:
                result.append({**item, "enabled": True})
        return result

    def upsert_server(self, name: str, config: dict[str, Any]) -> None:
        save_mcp_server(self.config_path, name, config)
        self.reload()

    def remove_server(self, name: str) -> bool:
        removed = remove_mcp_server(self.config_path, name)
        if removed:
            self.reload()
        return removed

    def set_server_enabled(self, name: str, enabled: bool) -> bool:
        updated = set_mcp_server_enabled(self.config_path, name, enabled)
        if updated:
            self.reload()
        return updated

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


def _specs_revision(specs: list[McpServerSpec]) -> str:
    """汇总一代 MCP 声明及监视路径的修订值。"""
    import hashlib

    digest = hashlib.sha256()
    for spec in sorted(specs, key=lambda item: item.name):
        digest.update(spec.revision().encode())
    return digest.hexdigest()


def _default_description(name: str, tools: list[str]) -> str:
    if name == "mcp-docs":
        return "查询 MCP 官方文档和协议资料。"
    if tools:
        return f"提供 {len(tools)} 个工具，用于扩展 Agent 能力。"
    return "为 Agent 提供外部工具能力。"

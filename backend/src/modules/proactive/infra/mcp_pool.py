"""主动数据采集使用的 MCP 常驻连接池。"""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class McpClientPool:
    """为每个服务维护一条常驻 MCP 连接。"""

    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}
        self._servers: list[dict[str, Any]] = []

    def add_server(self, name: str, command: list[str], **kwargs) -> None:
        self._servers.append({"name": name, "command": command, **kwargs})

    async def connect_all(self) -> None:
        """并行连接全部已配置服务。"""
        if not self._servers:
            return
        results = await asyncio.gather(
            *[self._connect_one(s) for s in self._servers],
            return_exceptions=True,
        )
        for s, r in zip(self._servers, results):
            if isinstance(r, Exception):
                logger.warning("MCP pool connect failed for %s: %s", s["name"], r)

    async def _connect_one(self, server: dict) -> None:
        name = server["name"]
        if name in self._clients:
            return
        cmd = server.get("command", [])
        if not cmd:
            return
        process_env = None
        if server.get("env"):
            import os

            process_env = os.environ.copy()
            process_env.update(server["env"])
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=process_env,
            cwd=server.get("cwd"),
        )
        self._clients[name] = proc
        logger.info("MCP pool connected: %s", name)

    async def call(self, server_name: str, tool_name: str, params: dict | None = None) -> Any:
        """调用已连接服务上的指定工具。"""
        proc = self._clients.get(server_name)
        if proc is None:
            return None
        import json
        payload = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": params or {}},
        }) + "\n"
        proc.stdin.write(payload.encode())
        await proc.stdin.drain()
        line = await proc.stdout.readline()
        if line:
            return json.loads(line.decode())
        return None

    async def close_all(self) -> None:
        for proc in self._clients.values():
            try:
                proc.terminate()
            except Exception:
                pass
        self._clients.clear()


class RegistryMcpPool:
    """把统一 MCP 注册表适配为主动链路的异步连接池协议。"""

    def __init__(self, registry) -> None:
        self._registry = registry

    async def connect_all(self) -> None:
        """连接由宿主注册表统一维护，这里无需重复启动进程。"""

    async def call(self, server_name: str, tool_name: str, params: dict | None = None):
        # 注册表客户端按服务加锁，主动链路直接复用同一条常驻连接。
        return self._registry.call_tool(
            server_name,
            tool_name,
            params or {},
        )

    async def close_all(self) -> None:
        """连接所有权属于宿主注册表，主动链路停止时不关闭。"""

    @property
    def connected_names(self) -> set[str]:
        return set(self._registry.server_names)

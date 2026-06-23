"""McpClientPool: pool of persistent MCP connections for data fetch (spec 3e)."""

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class McpClientPool:
    """Pool of MCP client connections. Each server gets one persistent client."""

    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}
        self._servers: list[dict[str, Any]] = []

    def add_server(self, name: str, command: list[str], **kwargs) -> None:
        self._servers.append({"name": name, "command": command, **kwargs})

    async def connect_all(self) -> None:
        """Connect to all configured MCP servers in parallel."""
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
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._clients[name] = proc
        logger.info("MCP pool connected: %s", name)

    async def call(self, server_name: str, tool_name: str, params: dict = None) -> Any:
        """Call a tool on a connected MCP server."""
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

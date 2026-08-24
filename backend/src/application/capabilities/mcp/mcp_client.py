"""基于 stdio 常驻子进程的 MCP JSON-RPC 客户端。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import select
import subprocess
import threading
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class McpToolInfo:
    """MCP 服务暴露的工具元数据。"""

    name: str
    description: str = ""
    input_schema: dict[str, Any] | None = None


@dataclass(slots=True)
class McpServerInfo:
    """MCP initialize 响应中的服务信息。"""

    name: str
    version: str = ""


class McpClient:
    """维护一个 MCP stdio 服务及其串行 JSON-RPC 调用。"""

    def __init__(
        self,
        name: str,
        command: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        call_timeout: float = 60.0,
    ) -> None:
        self.name = name
        self.command = command
        self.env = env
        self.cwd = cwd
        self._call_timeout = max(1.0, call_timeout)
        self._process: subprocess.Popen[str] | None = None
        self._next_id = 1
        self._lock = threading.RLock()
        self._connected = False
        self._protocol_version: str | None = None
        self._discovered_tools: list[McpToolInfo] = []
        self._stderr_thread: threading.Thread | None = None

    @property
    def is_connected(self) -> bool:
        process = self._process
        return self._connected and process is not None and process.poll() is None

    @property
    def protocol_version(self) -> str | None:
        return self._protocol_version

    def _new_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id

    def start(self, timeout: float = 30.0) -> list[McpToolInfo]:
        """启动服务、完成握手并发现工具。"""
        with self._lock:
            if self.is_connected:
                return list(self._discovered_tools)
            if not self.command:
                raise ValueError(f"MCP server {self.name!r} 缺少启动命令")

            process_env = os.environ.copy()
            if self.env:
                process_env.update(self.env)
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
                env=process_env,
                cwd=self.cwd,
            )
            self._start_stderr_drain()
            logger.info("MCP subprocess started: %s (pid=%d)", self.name, self._process.pid)

            try:
                init_id = self._new_id()
                self._send({
                    "jsonrpc": "2.0",
                    "id": init_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "clientInfo": {"name": "flow-agent", "version": "1.0"},
                    },
                })
                initialize = self._recv(init_id, "initialize", timeout=timeout)
                self._protocol_version = (
                    initialize.get("result", {}).get("protocolVersion")
                )
                self._send({
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                })

                list_id = self._new_id()
                self._send({
                    "jsonrpc": "2.0",
                    "id": list_id,
                    "method": "tools/list",
                    "params": {},
                })
                response = self._recv(list_id, "tools/list", timeout=timeout)
                tools_data = response.get("result", {}).get("tools", [])
                self._discovered_tools = [
                    McpToolInfo(
                        name=str(item.get("name", "")),
                        description=str(item.get("description", "")),
                        input_schema=item.get("inputSchema"),
                    )
                    for item in tools_data
                    if isinstance(item, dict) and str(item.get("name", "")).strip()
                ]
                self._connected = True
                logger.info(
                    "MCP server %s: discovered %d tools",
                    self.name,
                    len(self._discovered_tools),
                )
                return list(self._discovered_tools)
            except Exception:
                self.stop()
                raise

    async def connect(self) -> list[McpToolInfo]:
        """异步兼容入口。"""
        return await asyncio.to_thread(self.start)

    def call_sync(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> str:
        """同步调用远端工具；单个服务内按锁串行收发。"""
        effective_timeout = timeout if timeout is not None else self._call_timeout
        with self._lock:
            if not self.is_connected:
                raise RuntimeError(f"MCP server {self.name!r} not connected")
            call_id = self._new_id()
            self._send({
                "jsonrpc": "2.0",
                "id": call_id,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            })
            try:
                response = self._recv(
                    call_id,
                    f"tools/call:{tool_name}",
                    timeout=effective_timeout,
                )
            except (TimeoutError, ConnectionError):
                # 超时后的迟到响应会污染下一次 JSON-RPC 调用，直接重启该服务。
                self.stop(timeout=1.0)
                raise
            if "error" in response:
                error = response["error"]
                message = error.get("message", error) if isinstance(error, dict) else error
                raise RuntimeError(f"MCP error ({self.name}/{tool_name}): {message}")
            rendered = _render_result(response.get("result", {}))
            logger.debug("MCP call completed[%s]: %s", self.name, tool_name)
            return rendered

    async def call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> str:
        """异步兼容入口。"""
        return await asyncio.to_thread(
            self.call_sync,
            tool_name,
            arguments,
            timeout=timeout,
        )

    def stop(self, timeout: float = 10.0) -> None:
        """终止服务进程，超时后强制结束。"""
        logger.debug("MCP client stop requested: %s", self.name)
        with self._lock:
            process = self._process
            self._connected = False
            self._protocol_version = None
            self._process = None
            if process is None:
                return
            if process.poll() is None:
                logger.debug("MCP client terminating process: %s", self.name)
                process.terminate()
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=timeout)
            logger.info("MCP server disconnected: %s", self.name)

    async def disconnect(self) -> None:
        """异步兼容入口。"""
        await asyncio.to_thread(self.stop)

    def _send(self, payload: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise ConnectionError(f"MCP server {self.name!r} not started")
        process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        process.stdin.flush()
        logger.debug("MCP send[%s]: %s", self.name, payload.get("method", "?"))

    def _recv(
        self,
        expected_id: int,
        stage: str,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdout is None:
            raise ConnectionError(f"MCP server {self.name!r} not started")
        while True:
            readable, _writable, _errors = select.select(
                [process.stdout],
                [],
                [],
                timeout if timeout is not None else self._call_timeout,
            )
            if not readable:
                raise TimeoutError(
                    f"MCP server {self.name!r} 响应超时 (stage={stage})"
                )
            line = process.stdout.readline()
            if not line:
                raise ConnectionError(
                    f"MCP server {self.name!r} 意外关闭输出 (stage={stage})"
                )
            text = line.strip()
            if not text:
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("MCP non-JSON line from %s: %s", self.name, text[:200])
                continue
            if "id" not in data:
                continue
            if data.get("id") != expected_id:
                logger.warning(
                    "MCP unexpected id from %s: expected=%d got=%s",
                    self.name,
                    expected_id,
                    data.get("id"),
                )
                continue
            logger.debug("MCP recv[%s]: id=%d stage=%s", self.name, expected_id, stage)
            return data

    def _start_stderr_drain(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return

        def drain() -> None:
            for line in process.stderr:
                text = line.strip()
                if text:
                    logger.warning("MCP stderr[%s]: %s", self.name, text[:500])

        self._stderr_thread = threading.Thread(
            target=drain,
            name=f"mcp-stderr:{self.name}",
            daemon=True,
        )
        self._stderr_thread.start()


def _render_result(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        content = result.get("content", [])
        if isinstance(content, list):
            return "\n".join(
                str(block.get("text", block)) if isinstance(block, dict) else str(block)
                for block in content
            )
    return json.dumps(result, ensure_ascii=False)

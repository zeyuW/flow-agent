"""MCP 客户端：通过 stdio 子进程与 MCP server 通信，实现 JSON-RPC 协议。

实现 spec 2c-2f 和 3b-3f：
- 2c: asyncio.create_subprocess_exec 启动子进程
- 2d: initialize 握手（协议版本 2024-11-05）
- 2e: tools/list 方法调用
- 2f: 工具发现结果
- 3b: tools/call JSON-RPC 请求
- 3c: 接收与 call_id 匹配的响应
- 3d: 解析响应（错误 / content 数组）
- 3e: _send() 通过 stdin 写入
- 3f: _recv() 通过 stdout readline 读取
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 流缓冲区限制
_STREAM_LIMIT = 2**20  # 1 MiB


@dataclass(slots=True)
class McpToolInfo:
    """MCP server 暴露的工具元数据。"""

    name: str
    description: str = ""
    input_schema: dict[str, Any] | None = None


@dataclass(slots=True)
class McpServerInfo:
    """MCP server 信息（initialize 响应中返回）。"""

    name: str
    version: str = ""


class McpClient:
    """MCP 客户端：管理一个 MCP server 的 stdio 子进程连接。

    生命周期：
    1. connect()    — 启动子进程 → initialize 握手 → tools/list
    2. call()       — 发送 tools/call 请求 → 接收响应
    3. disconnect() — terminate/kill 子进程

    所有 async 方法可从同步上下文通过 asyncio.run() 调用。
    """

    def __init__(
        self,
        name: str,
        command: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        self.name = name
        self.command = command
        self.env = env
        self.cwd = cwd
        self._process: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._recv_timeout = 60.0
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._process is not None

    def _new_id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    # ── 连接 ──

    async def connect(self) -> list[McpToolInfo]:
        """建立 MCP server 连接（spec 2b-2f）。

        1. 启动子进程（spec 2c）
        2. JSON-RPC initialize 握手（spec 2d）
        3. tools/list 发现工具（spec 2e）
        4. 创建 McpToolWrapper 列表（spec 2f）

        Returns:
            发现的工具信息列表。
        """
        # 2c: 启动 stdio 子进程
        proc_env = None
        if self.env:
            import os
            proc_env = os.environ.copy()
            proc_env.update(self.env)

        self._process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=proc_env,
            cwd=self.cwd,
            limit=_STREAM_LIMIT,
        )
        logger.info("MCP subprocess started: %s (pid=%d)", self.name, self._process.pid)

        # 2d: JSON-RPC initialize 握手
        init_id = self._new_id()
        await self._send({
            "jsonrpc": "2.0",
            "id": init_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "flow-agent", "version": "1.0"},
            },
        })
        init_resp = await self._recv(expected_id=init_id, stage="initialize")

        # 发送 initialized 通知
        await self._send({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })
        logger.info("MCP handshake complete: %s", self.name)

        # 2e: tools/list 获取工具
        list_id = self._new_id()
        await self._send({
            "jsonrpc": "2.0",
            "id": list_id,
            "method": "tools/list",
            "params": {},
        })
        list_resp = await self._recv(expected_id=list_id, stage="tools/list")

        tools_data = list_resp.get("result", {}).get("tools", [])
        tool_infos: list[McpToolInfo] = []
        for td in tools_data:
            tool_infos.append(McpToolInfo(
                name=td.get("name", ""),
                description=td.get("description", ""),
                input_schema=td.get("inputSchema"),
            ))

        self._connected = True
        logger.info("MCP server %s: discovered %d tools", self.name, len(tool_infos))
        return tool_infos

    # ── 工具调用 (spec 3) ──

    async def call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> str:
        """调用 MCP server 的工具（spec 3a-3d）。

        1. 构造 tools/call JSON-RPC 请求（spec 3b）
        2. 接收匹配 call_id 的响应（spec 3c）
        3. 解析响应：错误处理 + content 数组提取（spec 3d）
        """
        if not self.is_connected:
            raise RuntimeError(f"MCP server {self.name!r} not connected")

        call_id = self._new_id()

        # 3b: 发送 tools/call 请求
        await self._send({
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        })

        # 3c: 接收响应
        resp = await self._recv(
            expected_id=call_id,
            stage=f"tools/call:{tool_name}",
            timeout=timeout,
        )

        # 3d: 解析响应
        if "error" in resp:
            err = resp["error"]
            return f"MCP error ({self.name}/{tool_name}): {err.get('message', err)}"

        result = resp.get("result", {})
        content = result.get("content", [])

        if isinstance(content, list):
            # 按 MCP 协议，content 是内容块数组
            return "\n".join(
                block.get("text", str(block))
                if isinstance(block, dict)
                else str(block)
                for block in content
            )

        # Fallback: 纯文本结果
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False)

    # ── 底层通信 (spec 3e-3f) ──

    async def _send(self, payload: dict[str, Any]) -> None:
        """通过 stdin 发送 JSON-RPC 消息（spec 3e）。"""
        if self._process is None or self._process.stdin is None:
            raise ConnectionError(f"MCP server {self.name!r} not started")
        data = json.dumps(payload, ensure_ascii=False) + "\n"
        self._process.stdin.write(data.encode("utf-8"))
        await self._process.stdin.drain()
        logger.debug("MCP send[%s]: %s", self.name, payload.get("method", "?"))

    async def _recv(
        self,
        expected_id: int,
        stage: str = "",
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """从 stdout 读取一行 JSON-RPC 响应（spec 3f）。

        跳过通知消息（无 id 字段），只返回匹配 expected_id 的响应。
        """
        effective_timeout = timeout if timeout is not None else self._recv_timeout

        if self._process is None or self._process.stdout is None:
            raise ConnectionError(f"MCP server {self.name!r} not started")

        while True:
            try:
                line = await asyncio.wait_for(
                    self._process.stdout.readline(),
                    timeout=effective_timeout,
                )
            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"MCP server {self.name!r} timed out ({effective_timeout}s) "
                    f"during {stage or 'recv'}"
                )

            if not line:
                raise ConnectionError(
                    f"MCP server {self.name!r} 意外关闭了 stdout "
                    f"(stage={stage or 'recv'})"
                )

            text = line.decode("utf-8").strip()
            if not text:
                continue

            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("MCP non-JSON line from %s: %s", self.name, text[:200])
                continue

            # 跳过通知（无 id）
            if "id" not in data:
                logger.debug("MCP notification from %s: %s", self.name, data.get("method", "?"))
                continue

            # 检查是否匹配
            if data.get("id") != expected_id:
                logger.warning(
                    "MCP unexpected id from %s: expected=%d got=%s",
                    self.name,
                    expected_id,
                    data.get("id"),
                )
                continue

            logger.debug("MCP recv[%s]: id=%d", self.name, expected_id)
            return data

    # ── 断开连接 (spec 4d) ──

    async def disconnect(self) -> None:
        """终止子进程（spec 4d）：先 terminate，超时则 kill。"""
        if self._process is None:
            return

        self._connected = False

        try:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
        except ProcessLookupError:
            pass  # 已经退出

        logger.info("MCP server disconnected: %s", self.name)
        self._process = None

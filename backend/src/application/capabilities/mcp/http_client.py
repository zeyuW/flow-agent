"""MCP Streamable HTTP 客户端的最小实现。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from application.capabilities.mcp.mcp_client import McpToolInfo, _render_result


@dataclass(slots=True)
class McpHttpClient:
    """通过 MCP Streamable HTTP 端点发现并调用工具。"""

    name: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    call_timeout: float = 60.0
    _client: httpx.Client | None = None
    _session_id: str | None = None
    _next_id: int = 1
    _connected: bool = False
    _discovered_tools: list[McpToolInfo] = field(default_factory=list)

    @property
    def command(self) -> list[str]:
        return [self.url]

    @property
    def is_connected(self) -> bool:
        return self._connected

    def start(self, timeout: float = 30.0) -> list[McpToolInfo]:
        """完成 MCP 初始化并发现远程工具。"""
        if self.is_connected:
            return list(self._discovered_tools)
        self._client = httpx.Client(
            timeout=max(1.0, timeout),
            headers={
                "Accept": "application/json, text/event-stream",
                **self.headers,
            },
        )
        try:
            self._request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "clientInfo": {"name": "flow-agent", "version": "1.0"},
                },
                timeout,
            )
            self._request("notifications/initialized", {}, timeout, notify=True)
            response = self._request("tools/list", {}, timeout)
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
            return list(self._discovered_tools)
        except Exception:
            self.stop()
            raise

    def call_sync(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> str:
        """调用远程 MCP 工具并渲染文本结果。"""
        if not self.is_connected:
            raise RuntimeError(f"MCP server {self.name!r} not connected")
        response = self._request(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
            timeout or self.call_timeout,
        )
        return _render_result(response.get("result", {}))

    def stop(self, timeout: float = 10.0) -> None:
        del timeout
        self._connected = False
        if self._client is not None:
            self._client.close()
            self._client = None
        self._session_id = None

    def _request(
        self,
        method: str,
        params: dict[str, Any],
        timeout: float,
        *,
        notify: bool = False,
    ) -> dict[str, Any]:
        if self._client is None:
            raise ConnectionError(f"MCP server {self.name!r} not started")
        request: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not notify:
            request["id"] = self._next_id
            self._next_id += 1
        request["params"] = params
        headers = {"MCP-Protocol-Version": "2024-11-05"}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        response = self._client.post(
            self.url,
            json=request,
            headers=headers,
            timeout=max(1.0, timeout),
        )
        response.raise_for_status()
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id
        if notify:
            return {}
        return _parse_http_response(response)


def _parse_http_response(response: httpx.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" not in content_type:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("MCP HTTP 响应必须是 JSON 对象")
        return data
    for line in response.text.splitlines():
        if line.startswith("data:"):
            data = json.loads(line[5:].strip())
            if isinstance(data, dict) and "id" in data:
                return data
    raise ValueError("MCP HTTP SSE 响应中没有 JSON-RPC 数据")

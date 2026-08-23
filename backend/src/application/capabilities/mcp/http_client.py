"""兼容新旧版本的 MCP Streamable HTTP 客户端。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from application.capabilities.mcp.mcp_client import McpToolInfo, _render_result


MODERN_VERSION = "2026-07-28"
LEGACY_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
_MODERN_ERROR_CODES = {-32022, -32020, -32601}


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
    _protocol_version: str | None = None
    _modern: bool = False
    _discovered_tools: list[McpToolInfo] = field(default_factory=list)

    @property
    def command(self) -> list[str]:
        return [self.url]

    @property
    def is_connected(self) -> bool:
        return self._connected

    def start(self, timeout: float = 30.0) -> list[McpToolInfo]:
        """优先连接最新协议，失败后回退到历史版本。"""
        if self.is_connected:
            return list(self._discovered_tools)
        self._client = httpx.Client(
            timeout=max(1.0, timeout),
            headers={"Accept": "application/json, text/event-stream", **self.headers},
        )
        try:
            response = self._send_modern("tools/list", {}, timeout)
            if _status_code(response) < 400:
                self._protocol_version = MODERN_VERSION
                self._modern = True
                tools_data = _parse_http_response(response).get("result", {}).get(
                    "tools", []
                )
            elif _is_modern_error(response):
                supported = _supported_versions(response)
                legacy = [version for version in supported if version in LEGACY_VERSIONS]
                if _is_unsupported_version(response) and legacy:
                    tools_data = self._start_legacy(timeout, versions=tuple(legacy))
                else:
                    raise _unsupported_modern_error(response)
            else:
                tools_data = self._start_legacy(timeout)
            self._discovered_tools = _tools_from_data(tools_data)
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
        timeout = timeout or self.call_timeout
        if self._modern:
            response = self._send_modern(
                "tools/call", {"name": tool_name, "arguments": arguments}, timeout
            )
            response.raise_for_status()
            data = _parse_http_response(response)
        else:
            data = self._request_legacy(
                "tools/call", {"name": tool_name, "arguments": arguments}, timeout
            )
        return _render_result(data.get("result", {}))

    def stop(self, timeout: float = 10.0) -> None:
        del timeout
        self._connected = False
        self._modern = False
        self._protocol_version = None
        if self._client is not None:
            self._client.close()
            self._client = None
        self._session_id = None

    def _start_legacy(
        self,
        timeout: float,
        *,
        versions: tuple[str, ...] = LEGACY_VERSIONS,
    ) -> list[dict[str, Any]]:
        """使用 initialize 握手连接旧版 Streamable HTTP 服务。"""
        last_error: Exception | None = None
        for version in versions:
            try:
                initialize = self._request_legacy(
                    "initialize",
                    {
                        "protocolVersion": version,
                        "capabilities": {"tools": {}},
                        "clientInfo": {"name": "flow-agent", "version": "1.0"},
                    },
                    timeout,
                )
                negotiated = initialize.get("result", {}).get("protocolVersion")
                self._protocol_version = str(negotiated or version)
                self._request_legacy(
                    "notifications/initialized", {}, timeout, notify=True
                )
                return self._request_legacy("tools/list", {}, timeout).get(
                    "result", {}
                ).get("tools", [])
            except (httpx.HTTPStatusError, ValueError) as exc:
                last_error = exc
                self._session_id = None
        raise last_error or RuntimeError("MCP 旧版协议初始化失败")

    def _request_legacy(
        self,
        method: str,
        params: dict[str, Any],
        timeout: float,
        *,
        notify: bool = False,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if not notify:
            request["id"] = self._next_id
            self._next_id += 1
        request["params"] = params
        headers = {"MCP-Protocol-Version": self._protocol_version or LEGACY_VERSIONS[0]}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        response = self._post(request, headers, timeout)
        response.raise_for_status()
        self._save_session(response)
        return {} if notify else _parse_http_response(response)

    def _send_modern(
        self, method: str, params: dict[str, Any], timeout: float
    ) -> httpx.Response:
        request_id = self._next_id
        self._next_id += 1
        meta = {
            "io.modelcontextprotocol/protocolVersion": MODERN_VERSION,
            "io.modelcontextprotocol/clientInfo": {
                "name": "flow-agent",
                "version": "1.0",
            },
            "io.modelcontextprotocol/clientCapabilities": {},
        }
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": {**params, "_meta": meta},
        }
        headers = {"MCP-Protocol-Version": MODERN_VERSION, "Mcp-Method": method}
        if method == "tools/call":
            headers["Mcp-Name"] = str(params.get("name", ""))
        return self._post(request, headers, timeout)

    def _post(
        self, request: dict[str, Any], headers: dict[str, str], timeout: float
    ) -> httpx.Response:
        if self._client is None:
            raise ConnectionError(f"MCP server {self.name!r} not started")
        return self._client.post(
            self.url,
            json=request,
            headers=headers,
            timeout=max(1.0, timeout),
        )

    def _save_session(self, response: httpx.Response) -> None:
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id


def _status_code(response: httpx.Response) -> int:
    return int(getattr(response, "status_code", 200))


def _is_modern_error(response: httpx.Response) -> bool:
    if _status_code(response) < 400:
        return False
    try:
        error = response.json().get("error", {})
    except (ValueError, AttributeError, TypeError):
        return False
    return error.get("code") in _MODERN_ERROR_CODES


def _is_unsupported_version(response: httpx.Response) -> bool:
    try:
        return response.json().get("error", {}).get("code") == -32022
    except (ValueError, AttributeError, TypeError):
        return False


def _supported_versions(response: httpx.Response) -> list[str]:
    try:
        supported = response.json().get("error", {}).get("data", {}).get("supported", [])
    except (ValueError, AttributeError, TypeError):
        return []
    return [str(version) for version in supported if str(version).strip()]


def _unsupported_modern_error(response: httpx.Response) -> RuntimeError:
    try:
        error = response.json().get("error", {})
        message = str(error.get("message", "现代 MCP 协议不受支持"))
    except (ValueError, AttributeError, TypeError):
        message = "现代 MCP 协议不受支持"
    return RuntimeError(message)


def _tools_from_data(tools_data: Any) -> list[McpToolInfo]:
    return [
        McpToolInfo(
            name=str(item.get("name", "")),
            description=str(item.get("description", "")),
            input_schema=item.get("inputSchema"),
        )
        for item in tools_data
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    ]


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

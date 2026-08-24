import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

from application.capabilities.mcp.mcp_client import McpClient
from application.capabilities.mcp.http_client import McpHttpClient
from application.capabilities.mcp.config import (
    McpServerSpec,
    load_project_mcp_specs,
    load_mcp_config,
    remove_mcp_server,
    save_mcp_server,
    set_mcp_server_enabled,
)
from application.capabilities.mcp.server_registry import McpServerRegistry
from application.capabilities.plugins.plugin_loader import PluginManager
from application.capabilities.tools.registry import ToolRegistry


_SERVER_SOURCE = '''
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}}
    elif method == "tools/list":
        result = {"tools": [{
            "name": "echo",
            "description": "回显外部输入",
            "inputSchema": {"type": "object"},
        }]}
    elif method == "tools/call":
        text = request.get("params", {}).get("arguments", {}).get("text", "")
        result = {"content": [{"type": "text", "text": "external:" + text}]}
    else:
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
'''


def _write_external_config(tmp_path: Path) -> Path:
    server_dir = tmp_path / "demo-server"
    server_dir.mkdir()
    script = server_dir / "server.py"
    script.write_text(_SERVER_SOURCE, encoding="utf-8")
    config = tmp_path / ".flow" / "mcp.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({
        "schemaVersion": 1,
        "mcpServers": {
            "demo": {
                "enabled": True,
                "command": sys.executable,
                "args": [str(script)],
                "cwd": str(server_dir),
                "watchPaths": [str(script)],
            },
        },
    }), encoding="utf-8")
    return config


def test_project_config_is_created_empty(tmp_path: Path):
    config = tmp_path / ".flow" / "mcp.json"

    specs = load_project_mcp_specs(config)

    assert config.exists()
    assert specs == []
    raw = json.loads(config.read_text(encoding="utf-8"))
    assert raw == {"schemaVersion": 1, "mcpServers": {}}


def test_project_json_loads_external_server(tmp_path: Path):
    config = _write_external_config(tmp_path)

    specs = load_project_mcp_specs(config)

    assert [spec.name for spec in specs] == ["demo"]


def test_project_json_loads_streamable_http_server(tmp_path: Path):
    config = tmp_path / ".flow" / "mcp.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({
        "schemaVersion": 1,
        "mcpServers": {
            "docs": {
                "url": "https://example.com/mcp",
                "headers": {"Authorization": "Bearer test"},
            }
        },
    }), encoding="utf-8")

    specs = load_project_mcp_specs(config)

    assert specs[0].url == "https://example.com/mcp"
    assert specs[0].command == ()
    assert specs[0].headers == {"Authorization": "Bearer test"}


def test_mcp_config_can_save_toggle_and_remove_server(tmp_path: Path):
    config = tmp_path / ".flow" / "mcp.json"

    save_mcp_server(config, "weather", {
        "command": sys.executable,
        "args": ["server.py"],
        "env": {"API_KEY": "local"},
        "enabled": True,
    })
    assert load_mcp_config(config)["mcpServers"]["weather"]["command"] == sys.executable

    assert set_mcp_server_enabled(config, "weather", False) is True
    assert load_mcp_config(config)["mcpServers"]["weather"]["enabled"] is False
    assert remove_mcp_server(config, "weather") is True
    assert remove_mcp_server(config, "weather") is False


def test_http_mcp_client_discovers_and_calls_tools(monkeypatch):
    requests: list[dict] = []

    class Response:
        headers = {"mcp-session-id": "session-1"}

        def raise_for_status(self):
            return None

        def json(self):
            request = requests[-1]
            if request["method"] == "initialize":
                return {"jsonrpc": "2.0", "id": request["id"], "result": {"capabilities": {"tools": {}}}}
            if request["method"] == "tools/list":
                return {"jsonrpc": "2.0", "id": request["id"], "result": {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]}}
            return {"jsonrpc": "2.0", "id": request["id"], "result": {"content": [{"type": "text", "text": "remote:hello"}]}}

    class Client:
        def __init__(self, **kwargs):
            self.headers = kwargs["headers"]

        def post(self, url, json, **kwargs):
            requests.append(json)
            return Response()

        def close(self):
            return None

    monkeypatch.setattr("application.capabilities.mcp.http_client.httpx.Client", Client)
    client = McpHttpClient("remote", "https://example.com/mcp")

    assert [tool.name for tool in client.start()] == ["echo"]
    assert client.call_sync("echo", {"text": "hello"}) == "remote:hello"
    assert requests[0]["method"] == "tools/list"
    assert requests[-1]["method"] == "tools/call"
    client.stop()


def test_http_mcp_client_prefers_modern_streamable_http(monkeypatch):
    requests: list[tuple[dict, dict]] = []

    class Response:
        headers = {"content-type": "application/json"}
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            request = requests[-1][0]
            return {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]},
            }

    class Client:
        def __init__(self, **kwargs):
            self.headers = kwargs["headers"]

        def post(self, url, json, headers, **kwargs):
            requests.append((json, headers))
            return Response()

        def close(self):
            return None

    monkeypatch.setattr("application.capabilities.mcp.http_client.httpx.Client", Client)
    client = McpHttpClient("modern", "https://example.com/mcp")

    assert [tool.name for tool in client.start()] == ["echo"]
    assert requests[0][0]["method"] == "tools/list"
    assert requests[0][0]["params"]["_meta"][
        "io.modelcontextprotocol/protocolVersion"
    ] == "2026-07-28"
    assert requests[0][1]["MCP-Protocol-Version"] == "2026-07-28"
    assert requests[0][1]["Mcp-Method"] == "tools/list"
    client.stop()


def test_http_mcp_client_falls_back_to_legacy_streamable_http(monkeypatch):
    requests: list[tuple[dict, dict]] = []

    class Response:
        def __init__(self, request, headers):
            self.request = request
            self.headers_sent = headers
            self.status_code = (
                400
                if request["method"] == "tools/list"
                and headers.get("MCP-Protocol-Version") == "2026-07-28"
                else 200
            )
            if request["method"] == "notifications/initialized":
                self.status_code = 202
            self.headers = {"content-type": "application/json"}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "bad request", request=httpx.Request("POST", "https://example.com/mcp"), response=self
                )

        def json(self):
            if (
                self.request["method"] == "tools/list"
                and self.headers_sent.get("MCP-Protocol-Version") == "2026-07-28"
            ):
                return {"error": {"code": -32600, "message": "legacy server"}}
            if self.request["method"] == "tools/list":
                return {"jsonrpc": "2.0", "id": self.request["id"], "result": {
                    "tools": [{"name": "echo", "inputSchema": {"type": "object"}}]
                }}
            if self.request["method"] == "initialize":
                return {"jsonrpc": "2.0", "id": self.request["id"], "result": {
                    "protocolVersion": "2025-11-25", "capabilities": {"tools": {}}
                }}
            if self.request["method"] == "tools/call":
                return {"jsonrpc": "2.0", "id": self.request["id"], "result": {
                    "content": [{"type": "text", "text": "legacy:hello"}]
                }}
            return {}

    class Client:
        def __init__(self, **kwargs):
            self.headers = kwargs["headers"]

        def post(self, url, json, headers, **kwargs):
            requests.append((json, headers))
            return Response(json, headers)

        def close(self):
            return None

    monkeypatch.setattr("application.capabilities.mcp.http_client.httpx.Client", Client)
    client = McpHttpClient("legacy", "https://example.com/mcp")

    assert [tool.name for tool in client.start()] == ["echo"]
    assert requests[0][0]["method"] == "tools/list"
    assert any(request[0]["method"] == "initialize" for request in requests)
    assert client.call_sync("echo", {"text": "hello"}) == "legacy:hello"
    client.stop()


def test_http_mcp_client_resets_connection_after_socket_hang_up(monkeypatch):
    class Client:
        def __init__(self, **kwargs):
            pass

        def post(self, url, json, **kwargs):
            raise httpx.RemoteProtocolError(
                "socket hang up", request=httpx.Request("POST", url)
            )

        def close(self):
            return None

    monkeypatch.setattr("application.capabilities.mcp.http_client.httpx.Client", Client)
    client = McpHttpClient("remote", "https://example.com/mcp")
    client._client = Client()
    client._connected = True
    client._modern = True

    with pytest.raises(RuntimeError, match="连接已断开"):
        client.call_sync("echo", {})

    assert client.is_connected is False


def test_registry_discovers_and_calls_external_json_server(tmp_path: Path):
    config = _write_external_config(tmp_path)
    tools = ToolRegistry()
    registry = McpServerRegistry(config, tools, startup_timeout=5, call_timeout=5)
    try:
        registry.start()
        result = tools.execute("mcp__demo__echo", {"text": "hello"})
        assert result.ok is True
        assert result.content == "external:hello"
    finally:
        registry.stop_all()


def test_registry_keeps_healthy_servers_when_another_server_fails(tmp_path: Path):
    config = _write_external_config(tmp_path)
    raw = json.loads(config.read_text(encoding="utf-8"))
    raw["mcpServers"]["broken"] = {
        "enabled": True,
        "command": "/path/that/does/not/exist",
    }
    config.write_text(json.dumps(raw), encoding="utf-8")
    tools = ToolRegistry()
    registry = McpServerRegistry(config, tools, startup_timeout=5, call_timeout=5)

    try:
        registry.start()

        result = tools.execute("mcp__demo__echo", {"text": "healthy"})
        assert result.ok is True
        assert registry.list_configured_servers()[1]["error"]
    finally:
        registry.stop_all()


def test_registry_stop_all_terminates_external_server_process(tmp_path: Path):
    """MCP 注册表停止后，实际 stdio 子进程必须已经退出。"""

    config = _write_external_config(tmp_path)
    registry = McpServerRegistry(config, ToolRegistry(), startup_timeout=5, call_timeout=5)
    registry.start()
    client = registry._clients["demo"]
    process = client._process
    assert process is not None
    assert process.poll() is None

    registry.stop_all()

    assert process.poll() is not None
    assert client.is_connected is False


def test_registry_enable_failure_restores_previous_config(tmp_path: Path, monkeypatch):
    config = _write_external_config(tmp_path)
    registry = McpServerRegistry(config, ToolRegistry())
    monkeypatch.setattr(
        McpServerRegistry,
        "reload",
        lambda self: (_ for _ in ()).throw(RuntimeError("启动失败")),
    )

    with pytest.raises(RuntimeError, match="启动失败"):
        registry.set_server_enabled("demo", False)

    raw = json.loads(config.read_text(encoding="utf-8"))
    assert raw["mcpServers"]["demo"]["enabled"] is True


def test_failed_json_reload_keeps_previous_generation(tmp_path: Path):
    config = _write_external_config(tmp_path)
    tools = ToolRegistry()
    registry = McpServerRegistry(config, tools, startup_timeout=5, call_timeout=5)
    try:
        registry.start()
        raw = json.loads(config.read_text(encoding="utf-8"))
        raw["mcpServers"]["broken"] = {
            "enabled": True,
            "command": "/path/that/does/not/exist",
            "args": [],
        }
        config.write_text(json.dumps(raw), encoding="utf-8")

        try:
            registry.reload()
        except Exception:
            pass

        result = tools.execute("mcp__demo__echo", {"text": "still-alive"})
        assert result.ok is True
    finally:
        registry.stop_all()


def test_plugin_declares_mcp_server_with_private_data_dir(tmp_path: Path):
    plugins_dir = tmp_path / "plugins"
    plugin_dir = plugins_dir / "demo"
    data_dir = tmp_path / "plugin-data"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        '''from application.capabilities.mcp.config import McpServerSpec
from application.capabilities.plugins.plugin_base import Plugin

class DemoPlugin(Plugin):
    @classmethod
    def mcp_servers(cls):
        return [McpServerSpec(name="plugin-demo", command=("python", "server.py"))]
''',
        encoding="utf-8",
    )
    manager = PluginManager(
        plugins_dir,
        tool_registry=ToolRegistry(),
        workspace=tmp_path,
        plugin_data_dir=data_dir,
    )

    asyncio.run(manager.load_all())

    specs = manager.get_mcp_servers()
    assert specs[0].cwd == str(plugin_dir.resolve())
    assert specs[0].env["FLOW_PLUGIN_DATA_DIR"] == str((data_dir / "demo").resolve())


def test_mcp_timeout_marks_client_disconnected(monkeypatch):
    client = McpClient(name="demo", command=["unused"])
    client._connected = True
    client._process = type("Process", (), {"poll": lambda self: None})()
    monkeypatch.setattr(client, "_send", lambda payload: None)
    monkeypatch.setattr(
        client,
        "_recv",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("timeout")),
    )
    stopped = []

    def stop(timeout=10.0):
        stopped.append(timeout)
        client._connected = False
        client._process = None

    monkeypatch.setattr(client, "stop", stop)

    with pytest.raises(TimeoutError):
        client.call_sync("tool", {})

    assert stopped == [1.0]
    assert client.is_connected is False

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from flow_agent.mcp import builtin_server
from flow_agent.mcp.config import McpServerSpec, load_project_mcp_specs
from flow_agent.mcp.server_registry import McpServerRegistry
from flow_agent.plugins.plugin_loader import PluginManager
from flow_agent.tools.registry import ToolRegistry


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


def test_ai_news_uses_independent_fallback_before_google(monkeypatch):
    published_at = datetime.now(timezone.utc).isoformat()

    monkeypatch.setattr(builtin_server, "AI_FEEDS", (("直连源", "https://direct"),))
    monkeypatch.setattr(
        builtin_server,
        "fetch_feed",
        lambda source, url, hours: ([{
            "title": "OpenAI direct item",
            "url": "https://direct/item",
            "summary": "",
            "source": source,
            "published_at": published_at,
            "provider": "Direct RSS",
        }], None),
    )
    monkeypatch.setattr(
        builtin_server,
        "fetch_gdelt_news",
        lambda hours, limit: [{
            "title": f"AI fallback item {index}",
            "url": f"https://fallback/{index}",
            "summary": "",
            "source": "备用源",
            "published_at": published_at,
            "provider": "GDELT",
        } for index in range(9)],
    )

    def fail_google(hours, limit):
        raise AssertionError("独立备用源足量时不应继续请求 Google News")

    monkeypatch.setattr(builtin_server, "fetch_google_news", fail_google)

    result = json.loads(builtin_server.get_ai_news(limit=10, hours=24))

    assert result["count"] == 10
    assert {item["provider"] for item in result["items"]} == {
        "Direct RSS",
        "GDELT",
    }
    assert result["provider_errors"] == []


def test_ai_news_continues_after_independent_fallback_error(monkeypatch):
    published_at = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(builtin_server, "AI_FEEDS", (("直连源", "https://direct"),))
    monkeypatch.setattr(
        builtin_server,
        "fetch_feed",
        lambda source, url, hours: ([], None),
    )

    def fail_gdelt(hours, limit):
        raise RuntimeError("temporary error")

    monkeypatch.setattr(builtin_server, "fetch_gdelt_news", fail_gdelt)
    monkeypatch.setattr(
        builtin_server,
        "fetch_google_news",
        lambda hours, limit: [{
            "title": f"AI Google item {index}",
            "url": f"https://google/{index}",
            "summary": "",
            "source": "Google News",
            "published_at": published_at,
            "provider": "Google News RSS",
        } for index in range(10)],
    )

    result = json.loads(builtin_server.get_ai_news(limit=10, hours=24))

    assert result["count"] == 10
    assert result["provider_errors"] == ["GDELT: temporary error"]


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
        '''from flow_agent.mcp.config import McpServerSpec
from flow_agent.plugins.plugin_base import Plugin

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

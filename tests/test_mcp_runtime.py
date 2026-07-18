import asyncio
import json
import sys
from pathlib import Path

import pytest

from flow_agent.mcp.config import McpServerSpec, load_workspace_mcp_specs
from flow_agent.mcp.server_registry import McpServerRegistry
from flow_agent.plugins.plugin_loader import PluginManager
from flow_agent.proactive.mcp_pool import RegistryMcpPool
from flow_agent.tools.registry import ToolRegistry


_SERVER_SOURCE = '''
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "demo", "version": "1"},
        }
    elif method == "tools/list":
        result = {"tools": [{
            "name": "echo",
            "description": "回显外部输入",
            "inputSchema": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        }]}
    elif method == "tools/call":
        text = request.get("params", {}).get("arguments", {}).get("text", "")
        result = {"content": [{"type": "text", "text": "external:" + text}]}
    else:
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
'''


def _write_workspace_server(tmp_path: Path) -> tuple[Path, Path]:
    mcp_root = tmp_path / "mcp"
    server_dir = mcp_root / "demo-server"
    declarations = mcp_root / "servers"
    server_dir.mkdir(parents=True)
    declarations.mkdir(parents=True)
    script = server_dir / "server.py"
    script.write_text(_SERVER_SOURCE, encoding="utf-8")
    (declarations / "demo.toml").write_text(
        f'''schema_version = 1
name = "demo"
command = ["{sys.executable}", "server.py"]
cwd = "../demo-server"
watch_paths = ["../demo-server/server.py"]
''',
        encoding="utf-8",
    )
    return mcp_root, script


def test_workspace_mcp_loader_enforces_safe_root(tmp_path: Path):
    mcp_root, _script = _write_workspace_server(tmp_path)

    specs = load_workspace_mcp_specs(mcp_root)

    assert len(specs) == 1
    assert specs[0].name == "demo"
    assert Path(specs[0].cwd or "").is_relative_to(mcp_root)

    (mcp_root / "servers" / "escape.toml").write_text(
        '''schema_version = 1
name = "escape"
command = ["python", "server.py"]
cwd = "../../outside"
''',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="越出安全根目录"):
        load_workspace_mcp_specs(mcp_root)


def test_registry_discovers_and_calls_workspace_mcp_tool(tmp_path: Path):
    mcp_root, _script = _write_workspace_server(tmp_path)
    tools = ToolRegistry()
    registry = McpServerRegistry(
        config_path=mcp_root / "servers.json",
        tool_registry=tools,
        startup_timeout=5.0,
        call_timeout=5.0,
    )

    try:
        registry.start()

        assert registry.server_names == ["demo"]
        assert "mcp__demo__echo" in tools.list_tool_names()
        result = tools.execute("mcp__demo__echo", {"text": "hello"})
        assert result.ok is True
        assert result.content == "external:hello"

        pool = RegistryMcpPool(registry)
        proactive_result = asyncio.run(pool.call("demo", "echo", {"text": "tick"}))
        assert proactive_result == "external:tick"
        asyncio.run(pool.close_all())
    finally:
        registry.stop_all()


def test_failed_reload_keeps_previous_generation(tmp_path: Path):
    mcp_root, _script = _write_workspace_server(tmp_path)
    tools = ToolRegistry()
    registry = McpServerRegistry(
        config_path=mcp_root / "servers.json",
        tool_registry=tools,
        startup_timeout=5.0,
        call_timeout=5.0,
    )

    try:
        registry.start()
        (mcp_root / "servers" / "broken.toml").write_text(
            '''schema_version = 1
name = "broken"
command = ["/path/that/does/not/exist"]
''',
            encoding="utf-8",
        )

        with pytest.raises(Exception):
            registry.reload()

        result = tools.execute("mcp__demo__echo", {"text": "still-alive"})
        assert result.ok is True
        assert result.content == "external:still-alive"
    finally:
        registry.stop_all()


def test_reload_can_publish_empty_generation(tmp_path: Path):
    mcp_root, _script = _write_workspace_server(tmp_path)
    tools = ToolRegistry()
    registry = McpServerRegistry(
        config_path=mcp_root / "servers.json",
        tool_registry=tools,
        startup_timeout=5.0,
        call_timeout=5.0,
    )

    try:
        registry.start()
        (mcp_root / "servers" / "demo.toml").unlink()

        registry.reload()

        assert registry.server_names == []
        assert "mcp__demo__echo" not in tools.list_tool_names()
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
    assert len(specs) == 1
    assert specs[0].cwd == str(plugin_dir.resolve())
    assert specs[0].env["FLOW_PLUGIN_DATA_DIR"] == str((data_dir / "demo").resolve())

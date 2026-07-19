import asyncio
import json
from pathlib import Path

from flow_agent.background.runtime import InMemoryJobRegistry
from flow_agent.messaging.event_bus import Event, EventBus
from flow_agent.plugins.plugin_loader import PluginManager
from flow_agent.tools.registry import ToolRegistry


def _write_plugin(path: Path, version: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "plugin.py").write_text(
        f'''from flow_agent.background.jobs import JobSpec
from flow_agent.plugins.plugin_base import Plugin
from flow_agent.plugins.plugin_decorators import on_after_turn, on_tool_pre, tool

class Phase:
    name = "demo-phase"
    def on_before_turn(self, flow):
        flow.extensions["plugin_phase"] = "{version}"

class DemoPlugin(Plugin):
    def before_turn_modules(self):
        return [Phase()]

    def background_jobs(self):
        return [JobSpec(name="refresh", func=lambda: "job-{version}")]

    @tool(name="plugin_echo", description="插件回显")
    def echo(self, text: str):
        prefix = self.context.config.get("prefix", "{version}")
        return prefix + ":" + text

    @on_tool_pre(tool_name="plugin_echo")
    def rewrite(self, ctx):
        if ctx.arguments.get("text") == "rewrite":
            return {{"text": "changed"}}

    @on_after_turn()
    def after_turn(self, ctx):
        self.context.kv_store.increment("after_turn")
''',
        encoding="utf-8",
    )


def test_plugin_reconcile_updates_runtime_contributions_and_keeps_old_on_failure(
    tmp_path: Path,
):
    plugins_dir = tmp_path / "plugins"
    plugin_dir = plugins_dir / "demo"
    data_dir = tmp_path / "plugin-data"
    _write_plugin(plugin_dir, "v1")
    tools = ToolRegistry()
    jobs = InMemoryJobRegistry()
    events = EventBus()
    manager = PluginManager(
        plugins_dir,
        event_bus=events,
        tool_registry=tools,
        background_registry=jobs,
        workspace=tmp_path,
        plugin_data_dir=data_dir,
    )

    asyncio.run(manager.load_all())

    assert tools.execute("plugin_echo", {"text": "hello"}).content == "v1:hello"
    assert jobs.get("demo:refresh").func() == "job-v1"
    assert len(manager.get_phase_modules()) == 1
    outcome = manager.tool_hook_executor.execute_sync(
        "plugin_echo",
        {"text": "rewrite"},
    )
    assert outcome.modified_args == {"text": "changed"}

    events.publish(Event(event_type="before_turn"))
    config_dir = data_dir / "demo"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "plugin_config.json").write_text(
        json.dumps({"prefix": "configured"}),
        encoding="utf-8",
    )
    assert asyncio.run(manager.reconcile()) is True
    assert tools.execute("plugin_echo", {"text": "hello"}).content == "configured:hello"

    _write_plugin(plugin_dir, "v2")
    assert asyncio.run(manager.reconcile()) is True
    assert tools.execute("plugin_echo", {"text": "hello"}).content == "configured:hello"
    assert jobs.get("demo:refresh").func() == "job-v2"

    (config_dir / "plugin_config.json").write_text("{broken", encoding="utf-8")
    assert asyncio.run(manager.reconcile()) is False
    assert tools.execute("plugin_echo", {"text": "hello"}).content == "configured:hello"
    (config_dir / "plugin_config.json").write_text(
        json.dumps({"prefix": "configured"}),
        encoding="utf-8",
    )
    assert asyncio.run(manager.reconcile()) is True

    (plugin_dir / "plugin.py").write_text("这不是合法 Python", encoding="utf-8")
    assert asyncio.run(manager.reconcile()) is False
    assert tools.execute("plugin_echo", {"text": "hello"}).content == "configured:hello"
    assert jobs.get("demo:refresh").func() == "job-v2"

    asyncio.run(manager.shutdown_all())
    assert "plugin_echo" not in tools.list_tool_names()
    assert jobs.get("demo:refresh") is None


def test_lifecycle_subscriber_only_receives_matching_event(tmp_path: Path):
    plugins_dir = tmp_path / "plugins"
    plugin_dir = plugins_dir / "demo"
    data_dir = tmp_path / "plugin-data"
    _write_plugin(plugin_dir, "v1")
    events = EventBus()
    manager = PluginManager(
        plugins_dir,
        event_bus=events,
        tool_registry=ToolRegistry(),
        workspace=tmp_path,
        plugin_data_dir=data_dir,
    )
    asyncio.run(manager.load_all())

    events.publish(Event(event_type="before_turn"))
    events.publish(Event(event_type="after_turn"))

    kv = json.loads((data_dir / "demo" / ".kv.json").read_text(encoding="utf-8"))
    assert kv["after_turn"] == 1
    asyncio.run(manager.shutdown_all())


def test_plugin_hot_reload_uses_fresh_relative_imports(tmp_path: Path):
    plugin_dir = tmp_path / "plugins" / "relative"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "helper.py").write_text('VALUE = "v1"\n', encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(
        '''from .helper import VALUE
from flow_agent.plugins.plugin_base import Plugin
from flow_agent.plugins.plugin_decorators import tool

class RelativePlugin(Plugin):
    @tool(name="relative_value")
    def value(self):
        return VALUE
''',
        encoding="utf-8",
    )
    tools = ToolRegistry()
    manager = PluginManager(
        tmp_path / "plugins",
        tool_registry=tools,
        workspace=tmp_path,
    )
    asyncio.run(manager.load_all())
    assert tools.execute("relative_value", {}).content == "v1"

    (plugin_dir / "helper.py").write_text('VALUE = "version-two"\n', encoding="utf-8")
    assert asyncio.run(manager.reconcile()) is True
    assert tools.execute("relative_value", {}).content == "version-two"
    asyncio.run(manager.shutdown_all())

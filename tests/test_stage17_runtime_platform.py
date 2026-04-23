import json
import urllib.request
from dataclasses import asdict

from flow_agent.dashboard.api import DashboardServer
from flow_agent.dashboard.store import InMemoryDashboardStore
from flow_agent.registry.base import RegistryItem
from flow_agent.registry.catalog import RegistryCatalog
from flow_agent.runtime.models import RuntimeHealth, RuntimeUnitSnapshot
from flow_agent.runtime.service import RuntimeService, RuntimeUnit


def test_unified_event_store_adds_envelope_fields():
    store = InMemoryDashboardStore()
    store.record({"type": "turn_start", "session_id": "s1", "trace_id": "t1"})
    snap = store.snapshot()
    event = snap.turns[-1]
    assert event["type"] == "turn_start"
    assert event["session_id"] == "s1"
    assert event["trace_id"] == "t1"
    assert "timestamp" in event
    assert "correlation_id" in event


def test_runtime_service_snapshot_and_dashboard_runtime_api():
    store = InMemoryDashboardStore()
    runtime = RuntimeService(dashboard=store)
    runtime.register(
        RuntimeUnit(
            name="proactive",
            health_fn=lambda: RuntimeHealth(name="proactive", ok=True, detail="running=false"),
            snapshot_fn=lambda: RuntimeUnitSnapshot(name="proactive", running=False, details={}),
        )
    )
    server = DashboardServer(
        host="127.0.0.1",
        port=0,
        store=store,
        runtime_snapshot_provider=lambda: asdict(runtime.snapshot()),
    )
    server.start()
    port = server._server.server_address[1]  # type: ignore[union-attr]
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/runtime", timeout=2) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    assert payload["metrics"]["runtime_count"] == 1
    assert payload["runtimes"][0]["name"] == "proactive"
    server.stop()


def test_registry_catalog_enable_disable_and_metadata():
    catalog = RegistryCatalog()
    catalog.register(RegistryItem(name="tool.read_file", metadata={"kind": "tool"}))
    assert catalog.list()[0].enabled is True
    catalog.disable("tool.read_file")
    assert catalog.list()[0].enabled is False
    catalog.enable("tool.read_file")
    assert catalog.metadata("tool.read_file")["kind"] == "tool"

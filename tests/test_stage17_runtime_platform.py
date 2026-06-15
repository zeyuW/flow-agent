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
    store.record({"type": "retrieval", "items": 0, "session_id": "s1"})
    store.record({"type": "retrieval", "items": 2, "session_id": "s1"})
    store.record({"type": "tool_selection", "selected": 2, "available": 8})
    store.record({"type": "tool_result", "status": "ok", "tool": "read_file"})
    store.record({"type": "tool_result", "status": "failed", "tool": "read_file"})
    store.record({"type": "proactive_judge", "reason": "low_relevance", "session_id": "s1"})
    store.record({"type": "proactive_sent", "key": "k1", "session_id": "s1"})
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
    quality = payload["event_summary"]["quality"]
    assert quality["retrieval"]["total"] == 2
    assert quality["retrieval"]["hit"] == 1
    assert quality["tool_selection"]["total"] == 1
    assert quality["tool_selection"]["tool_failures"] == 1
    assert quality["proactive"]["sent"] == 1
    assert quality["proactive"]["top_block_reasons"]["low_relevance"] == 1
    assert "window_1h" in quality
    assert "window_24h" in quality
    assert "by_session" in quality
    assert quality["by_session"]["s1"]["retrieval_total"] == 2
    assert quality["by_session"]["s1"]["retrieval_hit_rate"] == 0.5
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/runtime/quality", timeout=2) as resp:
        quality_payload = json.loads(resp.read().decode("utf-8"))
    assert quality_payload["retrieval"]["total"] == 2
    assert quality_payload["proactive"]["sent"] == 1
    server.stop()


def test_registry_catalog_enable_disable_and_metadata():
    catalog = RegistryCatalog()
    catalog.register(RegistryItem(name="tool.read_file", metadata={"kind": "tool"}))
    assert catalog.list()[0].enabled is True
    catalog.disable("tool.read_file")
    assert catalog.list()[0].enabled is False
    catalog.enable("tool.read_file")
    assert catalog.metadata("tool.read_file")["kind"] == "tool"

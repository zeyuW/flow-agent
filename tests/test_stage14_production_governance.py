from pathlib import Path

from flow_agent.background.jobs import JobSpec
from flow_agent.background.runtime import BackgroundRuntime, InMemoryJobRegistry
from flow_agent.background.store import InMemoryJobStore
from flow_agent.config.loader import clear_settings_cache, load_settings
from flow_agent.facade.background import BackgroundFacade
from flow_agent.facade.memory import MemoryFacade
from flow_agent.infra.persistence import PersistenceManager
from flow_agent.memory.store import InMemoryMessageStore


def test_config_governance_fields_from_env(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("FLOW_AGENT_CHANNEL_HTTP_ENABLED", "true")
    monkeypatch.setenv("FLOW_AGENT_CHANNEL_HTTP_HOST", "0.0.0.0")
    monkeypatch.setenv("FLOW_AGENT_CHANNEL_HTTP_PORT", "9999")
    monkeypatch.setenv("FLOW_AGENT_JOBS_MAX_ASYNC_QUEUE", "7")
    monkeypatch.setenv("FLOW_AGENT_SUBAGENT_MAX_CONCURRENCY", "3")
    monkeypatch.setenv("FLOW_AGENT_CONFIG_VERSION", "v14")
    settings = load_settings()
    assert settings.channels.http_enabled is True
    assert settings.channels.http_host == "0.0.0.0"
    assert settings.channels.http_port == 9999
    assert settings.jobs.max_async_queue == 7
    assert settings.subagent.max_concurrency == 3
    assert settings.governance.config_version == "v14"


def test_persistence_manager_schema_and_cleanup(tmp_path: Path):
    db = tmp_path / "memory.db"
    pm = PersistenceManager(db)
    pm.initialize()
    # Insert old data.
    import sqlite3

    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO messages(session_id, role, content, created_at) VALUES(?, ?, ?, ?)",
            ("s1", "user", "hello", "2000-01-01T00:00:00+00:00"),
        )
    pm.cleanup_retention(keep_days=1)
    counts = pm.consistency_check()
    assert counts["messages"] == 0


def test_background_queue_limit_and_facades():
    registry = InMemoryJobRegistry()
    store = InMemoryJobStore()
    runtime = BackgroundRuntime(registry=registry, store=store, max_async_queue=1)
    bg = BackgroundFacade(runtime=runtime)
    ran = {"n": 0}

    def job():
        ran["n"] += 1

    registry.register(JobSpec(name="j", func=job))
    bg.run_job("j")
    assert ran["n"] == 1


def test_memory_facade_roundtrip():
    facade = MemoryFacade(store=InMemoryMessageStore())
    facade.append_user_message("s1", "hi")
    facade.append_assistant_message("s1", "hello")
    hist = facade.list_history("s1")
    assert len(hist) == 2


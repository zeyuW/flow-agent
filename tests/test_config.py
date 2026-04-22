from flow_agent.config.loader import load_settings


def test_load_settings_from_env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.com")
    monkeypatch.setenv("LLM_SYSTEM_PROMPT", "test prompt")
    monkeypatch.setenv("FLOW_AGENT_MEMORY_DB_PATH", "/tmp/test-memory.db")
    monkeypatch.setenv("FLOW_AGENT_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("FLOW_AGENT_DEFAULT_SESSION", "s-test")
    monkeypatch.setenv("FLOW_AGENT_TOOLS_ENABLED", "false")
    monkeypatch.setenv("FLOW_AGENT_MAX_TOOL_STEPS", "7")
    monkeypatch.setenv("FLOW_AGENT_RETRIEVAL_ENABLED", "false")
    monkeypatch.setenv("FLOW_AGENT_RETRIEVAL_MAX_ITEMS", "3")
    monkeypatch.setenv("FLOW_AGENT_OBSERVE_ENABLED", "false")
    monkeypatch.setenv("FLOW_AGENT_TRACE_PATH", "/tmp/trace.jsonl")
    monkeypatch.setenv("FLOW_AGENT_MEMORY_POLICY_ENABLED", "false")
    monkeypatch.setenv("FLOW_AGENT_MEMORY_MAX_MESSAGES", "9")
    monkeypatch.setenv("FLOW_AGENT_MEMORY_DEDUPE", "false")
    monkeypatch.setenv("FLOW_AGENT_PROACTIVE_ENABLED", "true")
    monkeypatch.setenv("FLOW_AGENT_PROACTIVE_INTERVAL_SECONDS", "15")
    monkeypatch.setenv("FLOW_AGENT_PROACTIVE_COOLDOWN_SECONDS", "120")
    monkeypatch.setenv("FLOW_AGENT_PROACTIVE_DEDUP_TTL_SECONDS", "3600")
    monkeypatch.setenv("FLOW_AGENT_PROACTIVE_SOURCE_FILE", "/tmp/proactive_items.txt")
    monkeypatch.setenv("FLOW_AGENT_PROACTIVE_TODO_FILE", "/tmp/todo_items.txt")
    monkeypatch.setenv("FLOW_AGENT_PROACTIVE_TASKS_FILE", "/tmp/tasks.txt")
    monkeypatch.setenv("FLOW_AGENT_PROACTIVE_RSS_FEED_FILES", "/tmp/a.xml,/tmp/b.xml")
    monkeypatch.setenv("FLOW_AGENT_PROACTIVE_WEB_SNAPSHOT_FILES", "/tmp/a.txt,/tmp/b.txt")
    monkeypatch.setenv("FLOW_AGENT_SKILLS_DIR", "/tmp/skills")
    monkeypatch.setenv("FLOW_AGENT_PROACTIVE_MIN_PRIORITY_TO_SEND", "0.8")
    monkeypatch.setenv("FLOW_AGENT_MCP_ENABLED", "true")
    monkeypatch.setenv("FLOW_AGENT_MCP_SERVERS", "ext-a,ext-b")

    settings = load_settings()

    assert settings.model.model == "test-model"
    assert settings.model.api_key == "test-key"
    assert settings.model.base_url == "https://example.com"
    assert settings.model.system_prompt == "test prompt"
    assert settings.storage.memory_db_path == "/tmp/test-memory.db"
    assert settings.logging.level == "DEBUG"
    assert settings.session.default_session_id == "s-test"
    assert settings.tooling.enabled is False
    assert settings.tooling.max_tool_steps == 7
    assert settings.retrieval.enabled is False
    assert settings.retrieval.max_items == 3
    assert settings.observe.enabled is False
    assert settings.observe.trace_path == "/tmp/trace.jsonl"
    assert settings.memory_policy.enabled is False
    assert settings.memory_policy.max_messages == 9
    assert settings.memory_policy.dedupe is False
    assert settings.proactive.enabled is True
    assert settings.proactive.interval_seconds == 15
    assert settings.proactive.cooldown_seconds == 120
    assert settings.proactive.dedup_ttl_seconds == 3600
    assert settings.proactive.source_file == "/tmp/proactive_items.txt"
    assert settings.proactive.todo_file == "/tmp/todo_items.txt"
    assert settings.proactive.tasks_file == "/tmp/tasks.txt"
    assert settings.proactive.rss_feed_files == ["/tmp/a.xml", "/tmp/b.xml"]
    assert settings.proactive.web_snapshot_files == ["/tmp/a.txt", "/tmp/b.txt"]
    assert settings.proactive.skills_dir == "/tmp/skills"
    assert settings.proactive.min_priority_to_send == 0.8
    assert settings.mcp.enabled is True
    assert [server.name for server in settings.mcp.servers or []] == ["ext-a", "ext-b"]

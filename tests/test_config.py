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

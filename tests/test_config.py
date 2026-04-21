from flow_agent.config.loader import load_settings


def test_load_settings_from_env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_ID", "test-model")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.com")
    monkeypatch.setenv("LLM_SYSTEM_PROMPT", "test prompt")
    monkeypatch.setenv("FLOW_AGENT_MEMORY_DB_PATH", "/tmp/test-memory.db")
    monkeypatch.setenv("FLOW_AGENT_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("FLOW_AGENT_DEFAULT_SESSION", "s-test")
    monkeypatch.setenv("FLOW_AGENT_TOOLS_ENABLED", "false")
    monkeypatch.setenv("FLOW_AGENT_MAX_TOOL_STEPS", "7")

    settings = load_settings()

    assert settings.model.model_id == "test-model"
    assert settings.model.api_key == "test-key"
    assert settings.model.base_url == "https://example.com"
    assert settings.model.system_prompt == "test prompt"
    assert settings.storage.memory_db_path == "/tmp/test-memory.db"
    assert settings.logging.level == "DEBUG"
    assert settings.session.default_session_id == "s-test"
    assert settings.tooling.enabled is False
    assert settings.tooling.max_tool_steps == 7

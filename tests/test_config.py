from flow_agent.config.loader import load_settings


def test_load_settings_from_env(monkeypatch):
    monkeypatch.setenv("FLOW_AGENT_MODEL", "test-model")
    monkeypatch.setenv("FLOW_AGENT_API_KEY", "test-key")
    monkeypatch.setenv("FLOW_AGENT_BASE_URL", "https://example.com")
    monkeypatch.setenv("FLOW_AGENT_SYSTEM_PROMPT", "test prompt")

    settings = load_settings()

    assert settings.model == "test-model"
    assert settings.api_key == "test-key"
    assert settings.base_url == "https://example.com"
    assert settings.system_prompt == "test prompt"

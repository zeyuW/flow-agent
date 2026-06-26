"""配置加载单元测试。"""

from flow_agent.config.loader import clear_settings_cache, load_settings


def test_load_settings_from_env(monkeypatch):
    clear_settings_cache()
    monkeypatch.setenv("FLOW_AGENT_CONFIG_FILE", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.com")
    monkeypatch.setenv("LLM_SYSTEM_PROMPT", "test prompt")
    monkeypatch.setenv("FLOW_AGENT_STORAGE_MEMORY_DB_PATH", "/tmp/test-memory.db")
    monkeypatch.setenv("FLOW_AGENT_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("FLOW_AGENT_SESSION_DEFAULT_ID", "s-test")
    monkeypatch.setenv("FLOW_AGENT_TOOLING_ENABLED", "false")
    monkeypatch.setenv("FLOW_AGENT_TOOLING_MAX_STEPS", "7")
    monkeypatch.setenv("FLOW_AGENT_RETRIEVAL_ENABLED", "false")
    monkeypatch.setenv("FLOW_AGENT_RETRIEVAL_MAX_ITEMS", "3")
    monkeypatch.setenv("FLOW_AGENT_OBSERVE_ENABLED", "false")
    monkeypatch.setenv("FLOW_AGENT_OBSERVE_TRACE_PATH", "/tmp/trace.jsonl")
    monkeypatch.setenv("FLOW_AGENT_MEMORY_POLICY_ENABLED", "false")
    monkeypatch.setenv("FLOW_AGENT_MEMORY_MAX_MESSAGES", "9")
    monkeypatch.setenv("FLOW_AGENT_MEMORY_DEDUPE", "false")
    monkeypatch.setenv("FLOW_AGENT_PROACTIVE_ENABLED", "true")
    monkeypatch.setenv("FLOW_AGENT_PROACTIVE_MAX_PER_DAY", "15")
    monkeypatch.setenv("FLOW_AGENT_PROACTIVE_MIN_INTERVAL", "120")
    monkeypatch.setenv("FLOW_AGENT_PROACTIVE_COOLDOWN", "600")
    monkeypatch.setenv("FLOW_AGENT_DRIFT_ENABLED", "true")
    monkeypatch.setenv("FLOW_AGENT_DRIFT_MAX_STEPS", "20")
    monkeypatch.setenv("FLOW_AGENT_MCP_ENABLED", "true")
    monkeypatch.setenv("FLOW_AGENT_MCP_SERVERS", "ext-a,ext-b")

    settings = load_settings(force_reload=True)

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
    assert settings.proactive.max_per_day == 15
    assert settings.proactive.min_interval == 120
    assert settings.proactive.cooldown == 600
    assert settings.drift.enabled is True
    assert settings.drift.max_steps == 20
    assert settings.mcp.enabled is True
    assert len(settings.mcp.servers) == 2


def test_load_settings_from_external_file(monkeypatch, tmp_path):
    clear_settings_cache()
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[channels]
http_enabled = true
http_host = "0.0.0.0"
http_port = 9900

[jobs]
max_async_queue = 9

[proactive]
max_per_day = 7
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("FLOW_AGENT_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("FLOW_AGENT_CHANNEL_HTTP_ENABLED", "")
    monkeypatch.setenv("FLOW_AGENT_CHANNEL_HTTP_HOST", "")
    monkeypatch.setenv("FLOW_AGENT_CHANNEL_HTTP_PORT", "")
    monkeypatch.setenv("FLOW_AGENT_JOBS_MAX_ASYNC_QUEUE", "")
    monkeypatch.setenv("FLOW_AGENT_PROACTIVE_MAX_PER_DAY", "")

    settings = load_settings(force_reload=True)

    assert settings.channels.http_enabled is True
    assert settings.channels.http_host == "0.0.0.0"
    assert settings.channels.http_port == 9900
    assert settings.jobs.max_async_queue == 9
    assert settings.proactive.max_per_day == 7


def test_load_settings_llm_routing_style_config(monkeypatch, tmp_path):
    clear_settings_cache()
    config_file = tmp_path / "llm.toml"
    config_file.write_text(
        """
[llm]
provider = "qwen"

[llm.main]
model = "qwen-max"
api_key = "qwen-key"
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
enable_thinking = true

[llm.fast]
model = "qwen-turbo"
api_key = "qwen-fast-key"
base_url = ""

[provider]
provider_fallback_enabled = false
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("FLOW_AGENT_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("LLM_API_KEY", "")
    settings = load_settings(force_reload=True)

    assert settings.model.model == "qwen-max"
    assert settings.model.api_key == "qwen-key"
    assert settings.model.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert settings.model.enable_thinking is True
    assert settings.provider.fast_model == "qwen-turbo"
    assert settings.provider.fast_api_key == "qwen-fast-key"
    assert settings.provider.provider_fallback_enabled is False


def test_settings_proxy(monkeypatch):
    from flow_agent.config.settings import settings
    monkeypatch.setenv("LLM_MODEL", "proxy-model")
    monkeypatch.setenv("LLM_API_KEY", "proxy-key")
    monkeypatch.setenv("FLOW_AGENT_CONFIG_FILE", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    clear_settings_cache()
    assert settings.model.model == "proxy-model"

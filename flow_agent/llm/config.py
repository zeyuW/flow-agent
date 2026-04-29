from flow_agent.config.settings import ModelSettings, ProviderSettings
from flow_agent.config.source_values import ConfigValues

# 有独立配置语义（llm.main / llm.fast 路由映射、主快模型字段组装），保留有意义，可随时调整。
def build_llm_model_settings(values: ConfigValues) -> ModelSettings:
    return ModelSettings(
        model=values.get_str("LLM_MODEL", ("llm", "main", "model"), "deepseek-chat"),
        api_key=values.get_str("LLM_API_KEY", ("llm", "main", "api_key"), ""),
        base_url=values.get_str(
            "LLM_BASE_URL",
            ("llm", "main", "base_url"),
            "https://api.deepseek.com/v1",
        ),
        system_prompt=values.get_str(
            "LLM_SYSTEM_PROMPT",
            ("llm", "main", "system_prompt"),
            "You are a helpful AI assistant.",
        ),
        enable_thinking=values.get_bool(
            "LLM_ENABLE_THINKING",
            ("llm", "main", "enable_thinking"),
            False,
        ),
    )


def build_llm_provider_settings(values: ConfigValues) -> ProviderSettings:
    return ProviderSettings(
        fast_model=values.get_str("FLOW_AGENT_FAST_MODEL", ("llm", "fast", "model"), "") or None,
        fast_api_key=values.get_str("FLOW_AGENT_FAST_API_KEY", ("llm", "fast", "api_key"), "") or None,
        fast_base_url=values.get_str("FLOW_AGENT_FAST_BASE_URL", ("llm", "fast", "base_url"), "") or None,
        provider_fallback_enabled=values.get_bool(
            "FLOW_AGENT_PROVIDER_FALLBACK_ENABLED",
            ("provider", "provider_fallback_enabled"),
            True,
        ),
    )

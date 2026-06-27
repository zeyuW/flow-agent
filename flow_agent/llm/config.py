from dataclasses import dataclass
from flow_agent.config.settings import ModelSettings, ProviderSettings
from flow_agent.config.source_values import ConfigValues


@dataclass
class EmbeddingSettings:
    """Embedding 模型配置。"""
    provider: str
    model: str
    api_key: str
    base_url: str


def _get_provider_env_key(provider: str) -> str:
    """根据提供商名称获取对应的环境变量名。"""
    provider_map = {
        "deepseek": "DEEPSEEK_API_KEY",
        "qwen": "QWEN_API_KEY",
    }
    return provider_map.get(provider, "")


# 有独立配置语义（llm.main / llm.fast 路由映射、主快模型字段组装），保留有意义，可随时调整。
def build_llm_model_settings(values: ConfigValues) -> ModelSettings:
    # 从 [llm.main] 直接读取配置
    provider = values.get_str("", ("llm", "main", "provider"), "deepseek")
    
    # 根据 provider 获取对应的环境变量名
    env_key = _get_provider_env_key(provider)
    
    # 优先从环境变量读取，其次从 config.toml 读取
    model = values.get_str("LLM_MODEL", ("llm", "main", "model"), "deepseek-chat")
    api_key = values.get_str(env_key, ("llm", "main", "api_key"), "")
    base_url = values.get_str("LLM_BASE_URL", ("llm", "main", "base_url"), "")
    
    return ModelSettings(
        model=model,
        api_key=api_key,
        base_url=base_url,
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


def build_embedding_settings(values: ConfigValues) -> EmbeddingSettings:
    """构建 Embedding 配置。"""
    provider = values.get_str("", ("embedding", "provider"), "qwen")
    model = values.get_str("", ("embedding", "model"), "text-embedding-v3")
    
    # 根据 provider 获取对应的环境变量名
    env_key = _get_provider_env_key(provider)
    
    # 优先从环境变量读取，其次从 config.toml 读取
    api_key = values.get_str(env_key, ("embedding", "api_key"), "")
    base_url = values.get_str("", ("embedding", "base_url"), "")
    
    return EmbeddingSettings(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )


def build_llm_provider_settings(values: ConfigValues) -> ProviderSettings:
    # 从 [llm.fast] 直接读取配置
    provider = values.get_str("", ("llm", "fast", "provider"), "")
    
    if not provider:
        # 兼容旧配置：如果没有设置 provider，使用原来的方式
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
    
    # 根据 provider 获取对应的环境变量名
    env_key = _get_provider_env_key(provider)
    
    # 优先从环境变量读取，其次从 config.toml 读取
    fast_model = values.get_str("FLOW_AGENT_FAST_MODEL", ("llm", "fast", "model"), "")
    fast_api_key = values.get_str(env_key, ("llm", "fast", "api_key"), "")
    fast_base_url = values.get_str("FLOW_AGENT_FAST_BASE_URL", ("llm", "fast", "base_url"), "")
    
    return ProviderSettings(
        fast_model=fast_model or None,
        fast_api_key=fast_api_key or None,
        fast_base_url=fast_base_url or None,
        provider_fallback_enabled=values.get_bool(
            "FLOW_AGENT_PROVIDER_FALLBACK_ENABLED",
            ("provider", "provider_fallback_enabled"),
            True,
        ),
    )

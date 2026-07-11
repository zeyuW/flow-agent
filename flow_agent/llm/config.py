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


def build_llm_model_settings(values: ConfigValues) -> ModelSettings:
    """构建 LLM 模型配置：仅从 config.toml 读取，不再使用环境变量。"""
    # 从 [llm.main] 直接读取配置
    provider = values.get_str("", ("llm", "main", "provider"), "deepseek")
    model = values.get_str("", ("llm", "main", "model"), "deepseek-chat")
    api_key = values.get_str("", ("llm", "main", "api_key"), "")
    base_url = values.get_str("", ("llm", "main", "base_url"), "")
    
    return ModelSettings(
        model=model,
        api_key=api_key,
        base_url=base_url,
        system_prompt=values.get_str(
            "",
            ("llm", "main", "system_prompt"),
            "You are a helpful AI assistant.",
        ),
        enable_thinking=values.get_bool(
            "",
            ("llm", "main", "enable_thinking"),
            False,
        ),
    )


def build_embedding_settings(values: ConfigValues) -> EmbeddingSettings:
    """构建 Embedding 配置：仅从 config.toml 读取，不再使用环境变量。"""
    provider = values.get_str("", ("embedding", "provider"), "qwen")
    model = values.get_str("", ("embedding", "model"), "text-embedding-v3")
    api_key = values.get_str("", ("embedding", "api_key"), "")
    base_url = values.get_str("", ("embedding", "base_url"), "")
    
    return EmbeddingSettings(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
    )


def build_llm_provider_settings(values: ConfigValues) -> ProviderSettings:
    """构建 LLM 提供者配置：仅从 config.toml 读取，不再使用环境变量。"""
    # 从 [llm.fast] 直接读取配置
    provider = values.get_str("", ("llm", "fast", "provider"), "")
    
    if not provider:
        # 兼容旧配置：如果没有设置 provider，使用原来的方式
        return ProviderSettings(
            fast_model=values.get_str("", ("llm", "fast", "model"), "") or None,
            fast_api_key=values.get_str("", ("llm", "fast", "api_key"), "") or None,
            fast_base_url=values.get_str("", ("llm", "fast", "base_url"), "") or None,
            provider_fallback_enabled=values.get_bool(
                "",
                ("provider", "provider_fallback_enabled"),
                True,
            ),
        )
    
    fast_model = values.get_str("", ("llm", "fast", "model"), "")
    fast_api_key = values.get_str("", ("llm", "fast", "api_key"), "")
    fast_base_url = values.get_str("", ("llm", "fast", "base_url"), "")
    
    return ProviderSettings(
        fast_model=fast_model or None,
        fast_api_key=fast_api_key or None,
        fast_base_url=fast_base_url or None,
        provider_fallback_enabled=values.get_bool(
            "",
            ("provider", "provider_fallback_enabled"),
            True,
        ),
    )

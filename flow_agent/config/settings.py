"""Pydantic 配置模型：统一定义所有可配置项及其默认值。"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── LLM ──

class ModelSettings(BaseModel):
    model: str
    api_key: str | None = None
    base_url: str | None = None
    system_prompt: str = "You are a helpful AI assistant."
    enable_thinking: bool = False


class ProviderSettings(BaseModel):
    fast_model: str | None = None
    fast_api_key: str | None = None
    fast_base_url: str | None = None
    provider_fallback_enabled: bool = True


# ── 存储 ──

class StorageSettings(BaseModel):
    memory_db_path: str = ".flow/memory.db"


# ── 日志 ──

class LoggingSettings(BaseModel):
    level: str = "INFO"


# ── 会话 ──

class SessionSettings(BaseModel):
    default_session_id: str = "default"
    max_history_messages: int = 500
    cache_size: int = 64
    undo_enabled: bool = True
    tool_result_max_chars: int = 10000


# ── 工具 ──

class ToolingSettings(BaseModel):
    enabled: bool = True
    max_tool_steps: int = 5
    tool_selection_max: int = 8


# ── 检索 ──

class RetrievalSettings(BaseModel):
    enabled: bool = True
    max_items: int = 6
    min_score: float = 0.18


# ── 可观测 ──

class ObserveSettings(BaseModel):
    enabled: bool = True
    trace_path: str = ".flow/trace.jsonl"


# ── 记忆策略 ──

class MemoryPolicySettings(BaseModel):
    enabled: bool = True
    max_messages: int = 200
    dedupe: bool = True


# ── 主动推送 ──

class ProactiveSettings(BaseModel):
    """主动消息推送配置 (spec proactive 1-6)。"""
    enabled: bool = False
    max_per_day: int = 5
    min_interval: float = 60.0
    max_interval: float = 1800.0
    cooldown: float = 120.0
    judge_model: str | None = None
    # 霍克斯过程配置
    hawkes_enabled: bool = True
    hawkes_base_intensity: float = 0.1
    hawkes_excitation_alpha: float = 0.5
    hawkes_decay_beta: float = 0.1
    hawkes_time_constant: float = 60.0
    telegram_target_user_id: str | None = None


# ── 漂移模式 ──

class DriftSettings(BaseModel):
    """漂移模式配置 (spec drift 1-5)。"""
    enabled: bool = False
    data_dir: str = ".flow/drift"
    min_interval_hours: float = 1.0
    max_steps: int = 10


# ── 通道 ──

class ChannelsSettings(BaseModel):
    # HTTP API（Web 页面后端）
    http_enabled: bool = False
    http_host: str = "127.0.0.1"
    http_port: int = 8788
    # Telegram Bot
    telegram_enabled: bool = False
    telegram_bot_token: str | None = None
    telegram_allowed_users: str = ""   # 逗号分隔的用户 ID 列表
    telegram_allowed_groups: str = ""  # 逗号分隔的群 ID 列表


# ── 后台任务 ──

class JobsSettings(BaseModel):
    max_async_queue: int = 64
    timeout_seconds: float = 30.0


# ── 子代理 ──

class SubagentSettings(BaseModel):
    max_concurrency: int = 2
    tasks_file: str = ".flow/subagent_tasks.jsonl"


# ── 人设 ──

class PersonaSettings(BaseModel):
    name: str = "FlowAgent"
    passive_tone: str = "professional, concise, helpful"
    proactive_tone: str = "friendly, brief, actionable"
    style: str = "structured"


# ── 提示词预算 ──

class PromptBudgetSettings(BaseModel):
    max_chars: int = 8000
    history_chars: int = 3000
    memory_chars: int = 1500
    tool_trace_chars: int = 1000


# ── 委托策略 ──

class DelegationPolicySettings(BaseModel):
    max_local_chars: int = 500
    enabled: bool = True


# ── 顶层设置 ──

class Settings(BaseModel):
    model: ModelSettings
    storage: StorageSettings
    logging: LoggingSettings
    session: SessionSettings
    tooling: ToolingSettings
    retrieval: RetrievalSettings
    observe: ObserveSettings = Field(default_factory=ObserveSettings)
    memory_policy: MemoryPolicySettings = Field(default_factory=MemoryPolicySettings)
    proactive: ProactiveSettings = Field(default_factory=ProactiveSettings)
    drift: DriftSettings = Field(default_factory=DriftSettings)
    channels: ChannelsSettings = Field(default_factory=ChannelsSettings)
    jobs: JobsSettings = Field(default_factory=JobsSettings)
    subagent: SubagentSettings = Field(default_factory=SubagentSettings)
    persona: PersonaSettings = Field(default_factory=PersonaSettings)
    provider: ProviderSettings = Field(default_factory=ProviderSettings)
    prompt_budget: PromptBudgetSettings = Field(default_factory=PromptBudgetSettings)
    delegation_policy: DelegationPolicySettings = Field(default_factory=DelegationPolicySettings)

    @property
    def model_name(self) -> str:
        return self.model.model

    @property
    def api_key(self) -> str:
        return self.model.api_key

    @property
    def base_url(self) -> str | None:
        return self.model.base_url

    @property
    def system_prompt(self) -> str:
        return self.model.system_prompt


class _SettingsProxy:
    """延迟单例设置访问器。"""

    def __getattr__(self, name: str):
        from flow_agent.config.loader import load_settings
        return getattr(load_settings(), name)

    def reload(self) -> Settings:
        from flow_agent.config.loader import load_settings
        return load_settings(force_reload=True)

    def get(self) -> Settings:
        from flow_agent.config.loader import load_settings
        return load_settings()


settings = _SettingsProxy()

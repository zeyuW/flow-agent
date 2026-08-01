from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenConfig(BaseModel):
    """所有运行配置的不可变严格基类。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ModelEndpointConfig(FrozenConfig):
    """一个可直接调用的模型端点。"""

    model: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    base_url: str | None = None


class MainModelConfig(ModelEndpointConfig):
    """主模型端点及对话行为参数。"""

    system_prompt: str = "You are a helpful AI assistant."
    enable_thinking: bool = True


class LLMConfig(FrozenConfig):
    """对话、快速判断和视觉模型配置。"""

    main: MainModelConfig
    fast: ModelEndpointConfig | None = None
    vision: ModelEndpointConfig | None = None
    fallback_enabled: bool = True


class EmbeddingConfig(FrozenConfig):
    """嵌入服务配置；空密钥表示沿用主模型凭据。"""

    provider: str = "qwen"
    model: str = "text-embedding-v3"
    api_key: str | None = None
    base_url: str | None = None


class StorageConfig(FrozenConfig):
    """持久化与出站恢复参数。"""

    memory_db_path: str = Field(default=".flow/data/memory.db", min_length=1)
    outbox_recovery_window_seconds: float = Field(default=0.0, ge=0.0)
    outbox_recovery_limit: int = Field(default=100, ge=1)


class LoggingConfig(FrozenConfig):
    """日志输出参数。"""

    level: str = Field(default="INFO", min_length=1)


class SessionConfig(FrozenConfig):
    """会话缓存、历史和撤销参数。"""

    default_session_id: str = Field(default="default", min_length=1)
    max_history_messages: int = Field(default=500, ge=1)
    cache_size: int = Field(default=64, ge=1)
    undo_enabled: bool = True
    tool_result_max_chars: int = Field(default=10000, ge=100)


class ToolingConfig(FrozenConfig):
    """工具选择和执行轮数参数。"""

    enabled: bool = True
    max_tool_steps: int = Field(default=5, ge=1)
    tool_selection_max: int = Field(default=8, ge=1)


class McpConfig(FrozenConfig):
    """MCP 外部工具运行参数。"""

    enabled: bool = True
    startup_timeout_seconds: float = Field(default=30.0, ge=1.0)
    call_timeout_seconds: float = Field(default=60.0, ge=1.0)


class RetrievalConfig(FrozenConfig):
    """检索数量和相关度参数。"""

    enabled: bool = True
    max_items: int = Field(default=5, ge=1)
    min_score: float = Field(default=0.18, ge=0.0, le=1.0)


class ObserveConfig(FrozenConfig):
    """运行追踪参数。"""

    enabled: bool = True
    trace_path: str = Field(default=".flow/logs/trace.jsonl", min_length=1)


class MemoryPolicyConfig(FrozenConfig):
    """会话记忆选择策略。"""

    enabled: bool = True
    max_messages: int = Field(default=100, ge=1)
    dedupe: bool = True


class MemoryMaintenanceConfig(FrozenConfig):
    """记忆沉淀与画像优化参数。"""

    enabled: bool = True
    consolidation_min_new_messages: int = Field(default=5, ge=1)
    recent_turns_limit: int = Field(default=8, ge=1)
    optimizer_enabled: bool = True
    optimizer_interval_seconds: int = Field(default=64800, ge=1)


class ProactiveConfig(FrozenConfig):
    """主动消息判断、节流、兴趣和状态参数。"""

    enabled: bool = False
    max_per_day: int = Field(default=10, ge=1)
    min_interval: float = Field(default=60.0, ge=1.0)
    max_interval: float = Field(default=600.0, ge=1.0)
    cooldown: float = Field(default=60.0, ge=0.0)
    judge_model: str | None = None
    hawkes_enabled: bool = True
    hawkes_base_intensity: float = Field(default=2.0, ge=0.0)
    hawkes_excitation_alpha: float = Field(default=0.5, ge=0.0)
    hawkes_decay_beta: float = Field(default=0.1, ge=0.0)
    hawkes_time_constant: float = Field(default=30.0, ge=1.0)
    telegram_target_user_id: str | None = None
    idle_enabled: bool = False
    idle_threshold_minutes: float = Field(default=120.0, ge=1.0)
    interest_topics: tuple[str, ...] = ()
    state_path: str = Field(default=".flow/data/proactive.db", min_length=1)
    trace_path: str = Field(default=".flow/logs/proactive.jsonl", min_length=1)

    @model_validator(mode="after")
    def validate_runtime_requirements(self) -> ProactiveConfig:
        if self.min_interval > self.max_interval:
            raise ValueError("主动推送最小间隔不能大于最大间隔")
        if self.enabled and not (self.telegram_target_user_id or "").strip():
            raise ValueError("启用主动推送时必须配置目标用户")
        return self


class DriftConfig(FrozenConfig):
    """漂移任务调度参数。"""

    enabled: bool = True
    data_dir: str = Field(default=".flow/drift", min_length=1)
    min_interval_hours: float = Field(default=24.0, ge=0.1)
    max_steps: int = Field(default=50, ge=1)


class ChannelsConfig(FrozenConfig):
    """控制台、HTTP 和 Telegram 接入参数。"""

    dashboard_enabled: bool = False
    dashboard_host: str = Field(default="127.0.0.1", min_length=1)
    dashboard_port: int = Field(default=9901, ge=1, le=65535)
    http_enabled: bool = False
    http_host: str = Field(default="127.0.0.1", min_length=1)
    http_port: int = Field(default=8788, ge=1, le=65535)
    telegram_enabled: bool = False
    telegram_bot_token: str | None = None
    telegram_allowed_users: str = ""
    telegram_allowed_groups: str = ""

    @model_validator(mode="after")
    def validate_telegram_credentials(self) -> ChannelsConfig:
        if not self.telegram_enabled:
            return self
        if not (self.telegram_bot_token or "").strip():
            raise ValueError("启用 Telegram 时必须配置机器人令牌")
        if not self.telegram_allowed_users.strip():
            raise ValueError("启用 Telegram 时必须配置允许访问的用户")
        return self


class JobsConfig(FrozenConfig):
    """后台异步任务队列参数。"""

    max_async_queue: int = Field(default=64, ge=1)
    max_async_workers: int = Field(default=4, ge=1)
    timeout_seconds: float = Field(default=30.0, ge=0.1)


class SubagentConfig(FrozenConfig):
    """委托子代理的并发与持久化参数。"""

    max_concurrency: int = Field(default=2, ge=1)
    tasks_file: str = Field(default=".flow/sessions/subagent_tasks.jsonl", min_length=1)


class PersonaConfig(FrozenConfig):
    """被动与主动线路共用的人设参数。"""

    name: str = Field(default="FlowAgent", min_length=1)
    passive_tone: str = Field(default="professional, concise, helpful", min_length=1)
    proactive_tone: str = Field(default="friendly, brief, actionable", min_length=1)
    style: str = Field(default="structured", min_length=1)


class PromptBudgetConfig(FrozenConfig):
    """提示词各组成部分的字符预算。"""

    max_chars: int = Field(default=8000, ge=2000)
    history_chars: int = Field(default=3000, ge=500)
    memory_chars: int = Field(default=1500, ge=200)
    tool_trace_chars: int = Field(default=1000, ge=200)


class DelegationPolicyConfig(FrozenConfig):
    """本地处理与委托之间的选择策略。"""

    max_local_chars: int = Field(default=500, ge=100)
    enabled: bool = True


class AppConfig(FrozenConfig):
    """一次加载得到的完整应用配置快照。"""

    llm: LLMConfig
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    session: SessionConfig = Field(default_factory=SessionConfig)
    tooling: ToolingConfig = Field(default_factory=ToolingConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    observe: ObserveConfig = Field(default_factory=ObserveConfig)
    memory_policy: MemoryPolicyConfig = Field(default_factory=MemoryPolicyConfig)
    memory: MemoryMaintenanceConfig = Field(default_factory=MemoryMaintenanceConfig)
    proactive: ProactiveConfig = Field(default_factory=ProactiveConfig)
    drift: DriftConfig = Field(default_factory=DriftConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    jobs: JobsConfig = Field(default_factory=JobsConfig)
    subagent: SubagentConfig = Field(default_factory=SubagentConfig)
    persona: PersonaConfig = Field(default_factory=PersonaConfig)
    prompt_budget: PromptBudgetConfig = Field(default_factory=PromptBudgetConfig)
    delegation_policy: DelegationPolicyConfig = Field(
        default_factory=DelegationPolicyConfig
    )

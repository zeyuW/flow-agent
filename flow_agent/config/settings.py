from __future__ import annotations

from pydantic import BaseModel, Field


class ModelSettings(BaseModel):
    model: str
    api_key: str = ""
    base_url: str | None = None
    system_prompt: str = "You are a helpful AI assistant."
    enable_thinking: bool = False


class StorageSettings(BaseModel):
    memory_db_path: str


class LoggingSettings(BaseModel):
    level: str = "INFO"


class SessionSettings(BaseModel):
    default_session_id: str = "default"


class ToolingSettings(BaseModel):
    enabled: bool = True
    max_tool_steps: int = 5


class RetrievalSettings(BaseModel):
    enabled: bool = True
    max_items: int = 6


class ObserveSettings(BaseModel):
    enabled: bool = True
    trace_path: str = ".flow_agent/trace.jsonl"


class MemoryPolicySettings(BaseModel):
    enabled: bool = True
    max_messages: int = 200
    dedupe: bool = True


class ProactiveSettings(BaseModel):
    enabled: bool = False
    interval_seconds: int = 60
    cooldown_seconds: int = 300
    dedup_ttl_seconds: int = 86400
    source_file: str = ".flow_agent/proactive_items.txt"
    todo_file: str = ".flow_agent/todo_items.txt"
    tasks_file: str = ".flow_agent/tasks.txt"
    rss_feed_files: list[str] = Field(default_factory=list)
    web_snapshot_files: list[str] = Field(default_factory=list)
    skills_dir: str = "skills"
    min_priority_to_send: float = 0.5
    qq_target_user_id: str = ""


class MCPServerSettings(BaseModel):
    name: str
    enabled: bool = True
    tools: list[str] = Field(default_factory=list)


class MCPSettings(BaseModel):
    enabled: bool = False
    servers: list[MCPServerSettings] = Field(default_factory=list)


class ChannelsSettings(BaseModel):
    cli_enabled: bool = True
    http_enabled: bool = False
    http_host: str = "127.0.0.1"
    http_port: int = 8788
    dashboard_enabled: bool = False
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8787
    qq_enabled: bool = False
    qq_host: str = "127.0.0.1"
    qq_port: int = 8790
    qq_api_base: str = "http://127.0.0.1:3000"
    qq_access_token: str = ""


class JobsSettings(BaseModel):
    max_async_queue: int = 64
    timeout_seconds: float = 30.0


class SubagentSettings(BaseModel):
    max_concurrency: int = 2
    tasks_file: str = ".flow_agent/subagent_tasks.jsonl"


class ConfigGovernanceSettings(BaseModel):
    config_version: str = "v1"
    external_config_path: str | None = None


class PersonaSettings(BaseModel):
    name: str = "FlowAgent"
    passive_tone: str = "professional, concise, helpful"
    proactive_tone: str = "friendly, brief, actionable"
    style: str = "structured"


class ProviderSettings(BaseModel):
    fast_model: str | None = None
    fast_api_key: str | None = None
    fast_base_url: str | None = None
    provider_fallback_enabled: bool = True


class PromptBudgetSettings(BaseModel):
    max_chars: int = 8000
    history_chars: int = 3000
    memory_chars: int = 1500
    tool_trace_chars: int = 1000


class DelegationPolicySettings(BaseModel):
    max_local_chars: int = 500
    enabled: bool = True


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
    channels: ChannelsSettings = Field(default_factory=ChannelsSettings)
    jobs: JobsSettings = Field(default_factory=JobsSettings)
    subagent: SubagentSettings = Field(default_factory=SubagentSettings)
    governance: ConfigGovernanceSettings = Field(default_factory=ConfigGovernanceSettings)
    persona: PersonaSettings = Field(default_factory=PersonaSettings)
    provider: ProviderSettings = Field(default_factory=ProviderSettings)
    prompt_budget: PromptBudgetSettings = Field(default_factory=PromptBudgetSettings)
    delegation_policy: DelegationPolicySettings = Field(default_factory=DelegationPolicySettings)
    mcp: MCPSettings = Field(default_factory=MCPSettings)

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
    """Lazy singleton settings accessor."""

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

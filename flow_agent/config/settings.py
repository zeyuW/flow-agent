from dataclasses import dataclass, field


@dataclass(slots=True)
class ModelSettings:
    model: str
    api_key: str
    base_url: str | None
    system_prompt: str


@dataclass(slots=True)
class StorageSettings:
    memory_db_path: str


@dataclass(slots=True)
class LoggingSettings:
    level: str = "INFO"


@dataclass(slots=True)
class SessionSettings:
    default_session_id: str = "default"


@dataclass(slots=True)
class ToolingSettings:
    enabled: bool = True
    max_tool_steps: int = 5


@dataclass(slots=True)
class RetrievalSettings:
    enabled: bool = True
    max_items: int = 6

'''事件记录器设置'''
@dataclass(slots=True)
class ObserveSettings:
    enabled: bool = True
    trace_path: str = ".flow_agent/trace.jsonl"


@dataclass(slots=True)
class MemoryPolicySettings:
    enabled: bool = True
    max_messages: int = 200
    dedupe: bool = True


@dataclass(slots=True)
class ProactiveSettings:
    enabled: bool = False
    interval_seconds: int = 60
    cooldown_seconds: int = 300
    dedup_ttl_seconds: int = 86400
    source_file: str = ".flow_agent/proactive_items.txt"
    todo_file: str = ".flow_agent/todo_items.txt"
    tasks_file: str = ".flow_agent/tasks.txt"
    rss_feed_files: list[str] | None = None
    web_snapshot_files: list[str] | None = None
    skills_dir: str = "skills"
    min_priority_to_send: float = 0.5
    qq_target_user_id: str = ""


@dataclass(slots=True)
class MCPServerSettings:
    name: str
    enabled: bool = True
    tools: list[str] | None = None


@dataclass(slots=True)
class MCPSettings:
    enabled: bool = False
    servers: list[MCPServerSettings] | None = None


@dataclass(slots=True)
class ChannelsSettings:
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


@dataclass(slots=True)
class JobsSettings:
    max_async_queue: int = 64
    timeout_seconds: float = 30.0


@dataclass(slots=True)
class SubagentSettings:
    max_concurrency: int = 2
    tasks_file: str = ".flow_agent/subagent_tasks.jsonl"


@dataclass(slots=True)
class ConfigGovernanceSettings:
    config_version: str = "v1"
    profile: str = "dev"
    external_config_path: str | None = None


@dataclass(slots=True)
class PersonaSettings:
    name: str = "FlowAgent"
    passive_tone: str = "professional, concise, helpful"
    proactive_tone: str = "friendly, brief, actionable"
    style: str = "structured"


@dataclass(slots=True)
class ProviderSettings:
    fast_model: str | None = None
    provider_fallback_enabled: bool = True


@dataclass(slots=True)
class PromptBudgetSettings:
    max_chars: int = 8000
    history_chars: int = 3000
    memory_chars: int = 1500
    tool_trace_chars: int = 1000


@dataclass(slots=True)
class DelegationPolicySettings:
    max_local_chars: int = 500
    enabled: bool = True


@dataclass(slots=True)
class Settings:
    model: ModelSettings
    storage: StorageSettings
    logging: LoggingSettings
    session: SessionSettings
    tooling: ToolingSettings
    retrieval: RetrievalSettings
    observe: ObserveSettings
    memory_policy: MemoryPolicySettings
    proactive: ProactiveSettings
    channels: ChannelsSettings = field(default_factory=ChannelsSettings)
    jobs: JobsSettings = field(default_factory=JobsSettings)
    subagent: SubagentSettings = field(default_factory=SubagentSettings)
    governance: ConfigGovernanceSettings = field(default_factory=ConfigGovernanceSettings)
    persona: PersonaSettings = field(default_factory=PersonaSettings)
    provider: ProviderSettings = field(default_factory=ProviderSettings)
    prompt_budget: PromptBudgetSettings = field(default_factory=PromptBudgetSettings)
    delegation_policy: DelegationPolicySettings = field(default_factory=DelegationPolicySettings)
    mcp: MCPSettings = field(default_factory=MCPSettings)

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

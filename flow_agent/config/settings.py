from dataclasses import dataclass


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
    min_priority_to_send: float = 0.5


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

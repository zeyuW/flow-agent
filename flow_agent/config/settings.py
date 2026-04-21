from dataclasses import dataclass


@dataclass(slots=True)
class ModelSettings:
    model_id: str
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
class Settings:
    model: ModelSettings
    storage: StorageSettings
    logging: LoggingSettings
    session: SessionSettings
    tooling: ToolingSettings
    retrieval: RetrievalSettings

    @property
    def model_id(self) -> str:
        return self.model.model_id

    @property
    def api_key(self) -> str:
        return self.model.api_key

    @property
    def base_url(self) -> str | None:
        return self.model.base_url

    @property
    def system_prompt(self) -> str:
        return self.model.system_prompt

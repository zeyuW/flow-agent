import os
from pathlib import Path

from dotenv import load_dotenv

from flow_agent.config.settings import (
    LoggingSettings,
    ModelSettings,
    SessionSettings,
    Settings,
    StorageSettings,
    ToolingSettings,
)


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env")

    model = ModelSettings(
        model_id=os.getenv("LLM_MODEL_ID", "deepseek-chat"),
        api_key=os.getenv("LLM_API_KEY", ""),
        base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        system_prompt=os.getenv(
            "LLM_SYSTEM_PROMPT",
            "You are a helpful AI assistant.",
        ),
    )
    storage = StorageSettings(
        memory_db_path=os.getenv(
            "FLOW_AGENT_MEMORY_DB_PATH",
            str(project_root / ".flow_agent" / "memory.db"),
        ),
    )
    logging = LoggingSettings(
        level=os.getenv("FLOW_AGENT_LOG_LEVEL", "INFO"),
    )
    session = SessionSettings(
        default_session_id=os.getenv("FLOW_AGENT_DEFAULT_SESSION", "default"),
    )
    tooling = ToolingSettings(
        enabled=os.getenv("FLOW_AGENT_TOOLS_ENABLED", "true").lower()
        not in {"0", "false", "no", "off"},
    )

    return Settings(
        model=model,
        storage=storage,
        logging=logging,
        session=session,
        tooling=tooling,
    )

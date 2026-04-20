import os
from pathlib import Path

from dotenv import load_dotenv

from flow_agent.config.settings import Settings


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env")

    model_id = os.getenv("LLM_MODEL_ID", "deepseek-chat")
    api_key = os.getenv("LLM_API_KEY", "")
    base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    system_prompt = os.getenv("LLM_SYSTEM_PROMPT", "You are a helpful AI assistant.")

    return Settings(
        model_id=model_id,
        api_key=api_key,
        base_url=base_url,
        system_prompt=system_prompt,
    )

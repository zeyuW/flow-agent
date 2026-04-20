from dataclasses import dataclass


@dataclass(slots=True)
class Settings:
    model_id: str
    api_key: str
    base_url: str | None = None
    system_prompt: str = "You are a helpful AI assistant."

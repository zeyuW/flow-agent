from dataclasses import dataclass
from typing import Protocol

from openai import OpenAI

from flow_agent.config.settings import Settings
@dataclass(slots=True)
class LLMResult:
    content: str


# LLMClient is a协议(Protocol)类, 用于规定LLM客户端必须实现的接口（如generate方法）。
# 它没有真正"继承"什么类，只是继承了typing.Protocol，
# 作用是用于类型检查和定义接口规范，让像OpenAILLMClient这类实现类可以被类型安全、灵活地替换和调用。

class LLMClient(Protocol):
    def generate(self, messages: list[dict[str, str]]) -> LLMResult:
        ...


class OpenAILLMClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.api_key:
            raise ValueError("API key is required")

        self.model_id = settings.model_id
        self.client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
        )

    def generate(self, messages: list[dict[str, str]]) -> LLMResult:
        response = self.client.chat.completions.create(
            model=self.model_id,
            messages=messages,
        )
        content = response.choices[0].message.content or ""
        return LLMResult(content=content)


class FakeLLMClient:
    def generate(self, messages: list[dict[str, str]]) -> LLMResult:
        last_user_message = next(
            (msg["content"] for msg in reversed(messages) if msg.get("role") == "user"),
            "",
        )
        return LLMResult(content=f"echo: {last_user_message}")

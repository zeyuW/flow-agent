from dataclasses import dataclass
import json
import logging
from typing import Any
from typing import Protocol

from openai import APIConnectionError, APIError, APITimeoutError, AuthenticationError, OpenAI

from flow_agent.config.settings import Settings


logger = logging.getLogger(__name__)
@dataclass(slots=True)
class LLMResult:
    content: str
    tool_calls: list["LLMToolCall"] | None = None


@dataclass(slots=True)
class LLMToolCall:
    id: str
    name: str
    arguments_json: str
    arguments: dict[str, str]


# LLMClient is a协议(Protocol)类, 用于规定LLM客户端必须实现的接口（如generate方法）。
# 它没有真正"继承"什么类，只是继承了typing.Protocol，
# 作用是用于类型检查和定义接口规范，让像OpenAILLMClient这类实现类可以被类型安全、灵活地替换和调用。

class LLMClient(Protocol):
    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResult:
        ...

# OpenAILLMClient 是 OpenAI 模型的客户端实现
class OpenAILLMClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.api_key:
            raise ValueError("API key is required")

        self.model = settings.model_name
        # 创建 OpenAI 客户端
        self.client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
        )

    # 生成文本
    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResult:
        try:
            request_kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
            }
            if tools:
                request_kwargs["tools"] = tools
            response = self.client.chat.completions.create(**request_kwargs)  # type: ignore[arg-type]
        except AuthenticationError as exc:
            logger.exception("LLM authentication failed, please check API key")
            return LLMResult(content="认证失败：请检查 API Key 是否正确。")
        except (APIConnectionError, APITimeoutError) as exc:
            logger.exception("LLM network request failed")
            return LLMResult(content="网络异常：暂时无法连接到模型服务，请稍后重试。")
        except APIError as exc:
            logger.exception("LLM API returned an error")
            return LLMResult(content="模型服务暂时不可用，请稍后重试。")
        except Exception:
            logger.exception("Unexpected error during LLM request")
            return LLMResult(content="发生未知错误，请稍后重试。")

        if not response.choices:
            logger.warning("LLM returned no choices")
            return LLMResult(content="模型没有返回有效内容，请重试一次。")

        message = response.choices[0].message
        raw_tool_calls = message.tool_calls or []
        parsed_tool_calls: list[LLMToolCall] = []
        for tool_call in raw_tool_calls:
            arguments_json = tool_call.function.arguments
            parsed_arguments = self._parse_tool_arguments(arguments_json)
            parsed_tool_calls.append(
                LLMToolCall(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    arguments_json=arguments_json,
                    arguments=parsed_arguments,
                )
            )

        content = message.content or ""
        if not parsed_tool_calls and not content.strip():
            logger.warning("LLM returned empty content")
            return LLMResult(content="模型返回了空内容，请重试一次。")

        return LLMResult(content=content, tool_calls=parsed_tool_calls or None)

    def _parse_tool_arguments(self, arguments_json: str) -> dict[str, str]:
        try:
            raw = json.loads(arguments_json)
        except json.JSONDecodeError:
            return {}
        if not isinstance(raw, dict):
            return {}
        normalized: dict[str, str] = {}
        for key, value in raw.items():
            if isinstance(key, str):
                normalized[key] = str(value)
        return normalized


class FakeLLMClient:
    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResult:
        last_user_message = next(
            (msg["content"] for msg in reversed(messages) if msg.get("role") == "user"),
            "",
        )
        return LLMResult(content=f"echo: {last_user_message}")

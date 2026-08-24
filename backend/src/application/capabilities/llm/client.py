from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import ContextVar
import json
import logging
from typing import Any, Callable, Iterator
from typing import Protocol

from openai import (
    AsyncOpenAI,
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
)

from infra.resilience import RetryPolicy, retry_call, with_fallback
from infra.config import ModelEndpointConfig

logger = logging.getLogger(__name__)
_llm_stage: ContextVar[str] = ContextVar("llm_stage", default="unknown")


@contextmanager
def llm_stage(stage: str):
    """标记当前 LLM 请求所属阶段，便于区分主 Agent 和子 Agent。"""

    token = _llm_stage.set(stage)
    try:
        yield
    finally:
        _llm_stage.reset(token)


@dataclass(slots=True)
class LLMResult:
    content: str
    tool_calls: list["LLMToolCall"] | None = None
    error: str | None = None
    error_type: str | None = None
    status_code: int | None = None
    stage: str = "unknown"


@dataclass(slots=True)
class LLMToolCall:
    id: str
    name: str
    arguments_json: str
    arguments: dict[str, Any]


# LLMClient is a协议(Protocol)类, 用于规定LLM客户端必须实现的接口（如generate方法）。
# 它没有真正"继承"什么类，只是继承了typing.Protocol，
# 作用是用于类型检查和定义接口规范，让像OpenAILLMClient这类实现类可以被类型安全、灵活地替换和调用。


class LLMClient(Protocol):
    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResult: ...

    def generate_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> LLMResult: ...


# OpenAILLMClient 是 OpenAI 模型的客户端实现
class OpenAILLMClient:
    def __init__(self, config: ModelEndpointConfig) -> None:
        self.model = config.model
        # 创建 OpenAI 客户端
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self.async_client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    # 生成文本
    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResult:
        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            request_kwargs["tools"] = tools

        def _request():
            return retry_call(
                lambda: self.client.chat.completions.create(**request_kwargs),  # type: ignore[arg-type]
                policy=RetryPolicy(
                    max_attempts=2, delay_seconds=0.1, backoff_factor=1.8
                ),
                should_retry=lambda exc: isinstance(
                    exc, (APIConnectionError, APITimeoutError)
                ),
            )

        try:
            response = with_fallback(
                _request,
                lambda exc: (_raise(exc)),
            )
        except AuthenticationError as exc:
            return _failed_result(
                "认证失败：请检查 API Key 是否正确。",
                exc,
                "LLM authentication failed, please check API key",
            )
        except (APIConnectionError, APITimeoutError) as exc:
            return _failed_result(
                "网络异常：暂时无法连接到模型服务，请稍后重试。",
                exc,
                "LLM network request failed",
            )
        except APIError as exc:
            return _failed_result("模型服务暂时不可用，请稍后重试。", exc, "LLM API returned an error")
        except Exception as exc:
            return _failed_result("发生未知错误，请稍后重试。", exc, "Unexpected error during LLM request")

        if not response.choices:
            logger.warning("LLM returned no choices")
            return LLMResult(content="模型没有返回有效内容，请重试一次。")

        message = response.choices[0].message
        raw_tool_calls: list[Any] = list(message.tool_calls or [])
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

    async def generate_async(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResult:
        """通过异步传输生成结果，使取消信号可抵达网络请求。"""

        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            request_kwargs["tools"] = tools
        try:
            response = await self.async_client.chat.completions.create(
                **request_kwargs,
            )
        except AuthenticationError as exc:
            return _failed_result(
                "认证失败：请检查 API Key 是否正确。",
                exc,
                "LLM authentication failed, please check API key",
            )
        except (APIConnectionError, APITimeoutError) as exc:
            return _failed_result(
                "网络异常：暂时无法连接到模型服务，请稍后重试。",
                exc,
                "LLM network request failed",
            )
        except APIError as exc:
            return _failed_result("模型服务暂时不可用，请稍后重试。", exc, "LLM API returned an error")
        except Exception as exc:
            return _failed_result("发生未知错误，请稍后重试。", exc, "Unexpected error during async LLM request")

        if not response.choices:
            logger.warning("LLM returned no choices")
            return LLMResult(content="模型没有返回有效内容，请重试一次。")

        message = response.choices[0].message
        parsed_tool_calls: list[LLMToolCall] = []
        for tool_call in list(message.tool_calls or []):
            arguments_json = tool_call.function.arguments
            parsed_tool_calls.append(
                LLMToolCall(
                    id=tool_call.id,
                    name=tool_call.function.name,
                    arguments_json=arguments_json,
                    arguments=self._parse_tool_arguments(arguments_json),
                )
            )
        content = message.content or ""
        if not parsed_tool_calls and not content.strip():
            logger.warning("LLM returned empty content")
            return LLMResult(content="模型返回了空内容，请重试一次。")
        return LLMResult(content=content, tool_calls=parsed_tool_calls or None)

    # 流式生成文本
    def generate_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> LLMResult:
        request_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            request_kwargs["tools"] = tools

        def _request():
            return retry_call(
                lambda: self.client.chat.completions.create(**request_kwargs),  # type: ignore[arg-type]
                policy=RetryPolicy(
                    max_attempts=2, delay_seconds=0.1, backoff_factor=1.8
                ),
                should_retry=lambda exc: isinstance(
                    exc, (APIConnectionError, APITimeoutError)
                ),
            )

        try:
            response = with_fallback(
                _request,
                lambda exc: (_raise(exc)),
            )
        except AuthenticationError as exc:
            return _failed_result(
                "认证失败：请检查 API Key 是否正确。",
                exc,
                "LLM authentication failed, please check API key",
            )
        except (APIConnectionError, APITimeoutError) as exc:
            return _failed_result(
                "网络异常：暂时无法连接到模型服务，请稍后重试。",
                exc,
                "LLM network request failed",
            )
        except APIError as exc:
            return _failed_result("模型服务暂时不可用，请稍后重试。", exc, "LLM API returned an error")
        except Exception as exc:
            return _failed_result("发生未知错误，请稍后重试。", exc, "Unexpected error during LLM request")

        full_content = ""
        tool_call_parts: dict[int, dict[str, str]] = {}

        try:
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    delta = chunk.choices[0].delta.content
                    full_content += delta
                    if on_delta:
                        on_delta(delta)

                # 工具参数会被拆成多个增量片段，需要按 index 重新组装。
                if chunk.choices and chunk.choices[0].delta.tool_calls:
                    for tool_call in chunk.choices[0].delta.tool_calls:
                        index = int(getattr(tool_call, "index", 0) or 0)
                        part = tool_call_parts.setdefault(
                            index,
                            {"id": "", "name": "", "arguments": ""},
                        )
                        call_id = getattr(tool_call, "id", None)
                        if call_id:
                            part["id"] = str(call_id)
                        function = getattr(tool_call, "function", None)
                        if function is None:
                            continue
                        name = getattr(function, "name", None)
                        if name:
                            part["name"] = str(name)
                        arguments = getattr(function, "arguments", None)
                        if arguments:
                            part["arguments"] += str(arguments)

        except Exception as e:
            logger.exception("Error during streaming")
            # 如果流式失败，回退到非流式
            return self.generate(messages, tools)

        parsed_tool_calls: list[LLMToolCall] = []
        for index in sorted(tool_call_parts):
            part = tool_call_parts[index]
            if not part["name"]:
                continue
            arguments_json = part["arguments"] or "{}"
            parsed_tool_calls.append(
                LLMToolCall(
                    id=part["id"] or f"stream_call_{index}",
                    name=part["name"],
                    arguments_json=arguments_json,
                    arguments=self._parse_tool_arguments(arguments_json),
                )
            )

        if parsed_tool_calls:
            return LLMResult(content=full_content, tool_calls=parsed_tool_calls)
        if full_content.strip():
            return LLMResult(content=full_content, tool_calls=None)

        logger.warning("流式模型返回空内容，回退到非流式请求")
        return self.generate(messages, tools)

    def _parse_tool_arguments(self, arguments_json: str) -> dict[str, Any]:
        try:
            raw = json.loads(arguments_json)
        except json.JSONDecodeError:
            return {}
        if not isinstance(raw, dict):
            return {}
        normalized: dict[str, Any] = {}
        for key, value in raw.items():
            if isinstance(key, str):
                normalized[key] = value
        return normalized


def _raise(exc: Exception):
    raise exc


def _failed_result(content: str, exc: Exception, message: str) -> LLMResult:
    status_code = getattr(exc, "status_code", None)
    logger.exception(
        "%s: stage=%s status_code=%s",
        message,
        _llm_stage.get(),
        status_code,
    )
    return LLMResult(
        content=content,
        error=str(exc),
        error_type=type(exc).__name__,
        status_code=status_code if isinstance(status_code, int) else None,
        stage=_llm_stage.get(),
    )


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

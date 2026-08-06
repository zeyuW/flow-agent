from dataclasses import dataclass
from typing import Any
from typing import Protocol

from application.capabilities.llm.client import LLMResult


class _ClientLike(Protocol):
    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResult:
        ...


@dataclass(slots=True)
class LLMRouter:
    """Main/Fast model routing with fallback."""

    main_client: _ClientLike
    fast_client: _ClientLike | None = None

    def generate_main(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResult:
        return self.main_client.generate(messages, tools=tools)

    async def generate_main_async(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResult:
        """通过主模型执行可取消的异步生成。"""

        generate_async = getattr(self.main_client, "generate_async", None)
        if not callable(generate_async):
            raise RuntimeError("主模型客户端不支持异步生成")
        return await generate_async(messages, tools=tools)

    def generate_fast(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResult:
        if self.fast_client is None:
            return self.main_client.generate(messages, tools=tools)
        try:
            return self.fast_client.generate(messages, tools=tools)
        except Exception:
            return self.main_client.generate(messages, tools=tools)

from dataclasses import dataclass
from typing import Any
from typing import Protocol


class _ClientLike(Protocol):
    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ):
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
    ):
        return self.main_client.generate(messages, tools=tools)

    def generate_fast(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ):
        if self.fast_client is None:
            return self.main_client.generate(messages, tools=tools)
        try:
            return self.fast_client.generate(messages, tools=tools)
        except Exception:
            return self.main_client.generate(messages, tools=tools)


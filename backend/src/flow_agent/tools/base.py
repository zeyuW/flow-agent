from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class ToolResult:
    ok: bool
    content: str


class Tool(Protocol):
    @property
    def name(self) -> str:
        ...

    @property
    def description(self) -> str:
        ...

    @property
    def input_schema(self) -> dict[str, Any]:
        ...

    def run(self, tool_input: dict[str, str]) -> ToolResult:
        ...

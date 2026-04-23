from dataclasses import dataclass

from flow_agent.tools.base import ToolResult
from flow_agent.tools.registry import ToolRegistry


@dataclass(slots=True)
class ToolFacade:
    registry: ToolRegistry

    def list(self) -> list[dict[str, str]]:
        return self.registry.list_tool_descriptions()

    def execute(self, tool_name: str, tool_input: dict[str, str]) -> ToolResult:
        return self.registry.execute(tool_name=tool_name, tool_input=tool_input)

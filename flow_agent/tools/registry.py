from typing import Any

from flow_agent.tools.base import Tool, ToolResult


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def list_tool_descriptions(self) -> list[dict[str, str]]:
        return [
            {"name": tool.name, "description": tool.description}
            for tool in self._tools.values()
        ]

    def execute(self, tool_name: str, tool_input: dict[str, str]) -> ToolResult:
        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(ok=False, content=f"Unknown tool: {tool_name}")
        return tool.run(tool_input)

    def list_openai_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in self._tools.values()
        ]

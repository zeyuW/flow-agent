from dataclasses import dataclass, field
from typing import Any
import re

from flow_agent.guard.guards import ToolGuard
from flow_agent.tools.base import Tool, ToolResult


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._guard: ToolGuard | None = None
        self._execution_policy = self.ToolExecutionPolicy()

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def list_tool_descriptions(self) -> list[dict[str, str]]:
        return [
            {"name": tool.name, "description": tool.description}
            for tool in self._tools.values()
        ]

    def list_tool_names(self) -> set[str]:
        return set(self._tools.keys())

    def set_guard(self, guard: ToolGuard) -> None:
        self._guard = guard

    @dataclass(slots=True)
    class ToolExecutionPolicy:
        default_max_retries: int = 0
        max_retries_by_risk: dict[str, int] = field(
            default_factory=lambda: {
                "read-only": 1,
                "write": 0,
                "external-side-effect": 0,
            }
        )
        risk_by_tool: dict[str, str] = field(default_factory=dict)

    def set_execution_policy(self, policy: ToolExecutionPolicy) -> None:
        self._execution_policy = policy

    def get_risk_level(self, tool_name: str) -> str:
        policy = getattr(self, "_execution_policy", None)
        if policy is None:
            return "read-only"
        return policy.risk_by_tool.get(tool_name, "read-only")

    def execute(self, tool_name: str, tool_input: dict[str, str]) -> ToolResult:
        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(ok=False, content=f"Unknown tool: {tool_name}")
        if self._guard is not None:
            decision = self._guard.check_tool(tool_name)
            if not decision.allowed:
                return ToolResult(ok=False, content=f"Guard blocked tool: {decision.reason}")
            decision = self._guard.check_tool_input(tool_name, tool_input)
            if not decision.allowed:
                return ToolResult(ok=False, content=f"Guard blocked input: {decision.reason}")
        return tool.run(tool_input)

    def execute_with_policy(self, tool_name: str, tool_input: dict[str, str]) -> tuple[ToolResult, dict[str, Any]]:
        policy = getattr(self, "_execution_policy", self.ToolExecutionPolicy())
        risk = self.get_risk_level(tool_name)
        retries = max(0, policy.max_retries_by_risk.get(risk, policy.default_max_retries))
        attempts = 0
        last_error = ""
        while attempts <= retries:
            attempts += 1
            try:
                return self.execute(tool_name=tool_name, tool_input=tool_input), {
                    "risk": risk,
                    "attempts": attempts,
                    "retries": retries,
                }
            except Exception as exc:
                last_error = str(exc)
                if attempts > retries:
                    break
        return ToolResult(ok=False, content=f"Tool `{tool_name}` failed after retries: {last_error}"), {
            "risk": risk,
            "attempts": attempts,
            "retries": retries,
            "failed_with_exception": True,
        }

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

    def select_openai_tools(self, user_input: str, *, max_tools: int = 8) -> list[dict[str, Any]]:
        all_tools = self.list_openai_tools()
        if not user_input.strip() or len(all_tools) <= max_tools:
            return all_tools[:max_tools]
        query_tokens = _tokenize(user_input)
        scored: list[tuple[float, dict[str, Any]]] = []
        for item in all_tools:
            function = item.get("function", {})
            tool_name = str(function.get("name", ""))
            description = str(function.get("description", ""))
            text = f"{tool_name} {description}"
            tool_tokens = _tokenize(text)
            overlap = len(query_tokens & tool_tokens)
            score = overlap / max(1, len(query_tokens))
            # Prefer core built-in tools when equally matched.
            if not tool_name.startswith("mcp:"):
                score += 0.05
            scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        picked = [item for score, item in scored if score > 0][:max_tools]
        if picked:
            return picked
        return all_tools[:max_tools]


_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text or "")}

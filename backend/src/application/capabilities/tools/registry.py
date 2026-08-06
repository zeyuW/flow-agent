from dataclasses import dataclass, field
from typing import Any
import re
import threading

from application.capabilities.tools.guard import ToolGuard
from application.capabilities.tools.base import Tool, ToolResult


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._lock = threading.RLock()
        self._guard: ToolGuard | None = None
        self._execution_policy = self.ToolExecutionPolicy()

    def register(self, tool: Tool) -> None:
        with self._lock:
            self._tools[tool.name] = tool

    def register_with_meta(self, tool, risk="read-only", source_type="", source_name=""):
        with self._lock:
            self._tools[tool.name] = tool
            if hasattr(self, '_execution_policy'):
                self._execution_policy.risk_by_tool[tool.name] = risk

    def unregister(self, tool_name):
        with self._lock:
            self._tools.pop(tool_name, None)
            if hasattr(self, '_execution_policy'):
                self._execution_policy.risk_by_tool.pop(tool_name, None)

    def replace_many(
        self,
        remove_names: set[str],
        additions: list[tuple[Any, str]],
    ) -> None:
        """在同一个锁内替换一组动态工具及其风险元数据。"""

        with self._lock:
            for name in remove_names:
                self._tools.pop(name, None)
                self._execution_policy.risk_by_tool.pop(name, None)
            for tool, risk in additions:
                self._tools[tool.name] = tool
                self._execution_policy.risk_by_tool[tool.name] = risk

    def list_tool_descriptions(self) -> list[dict[str, str]]:
        with self._lock:
            return [
                {"name": tool.name, "description": tool.description}
                for tool in self._tools.values()
            ]

    def list_tool_names(self) -> set[str]:
        with self._lock:
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
        with self._lock:
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
        with self._lock:
            tools = list(self._tools.values())
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in tools
        ]

    def select_openai_tools(self, user_input: str, *, max_tools: int = 8) -> list[dict[str, Any]]:
        all_tools = self.list_openai_tools()
        if not user_input.strip() or len(all_tools) <= max_tools:
            return all_tools[:max_tools]
        normalized_input = user_input.lower()
        explicitly_named = [
            item
            for item in all_tools
            if str(item.get("function", {}).get("name", "")).lower()
            in normalized_input
        ]
        explicitly_named_names = {
            str(item.get("function", {}).get("name", ""))
            for item in explicitly_named
        }
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
            # 匹配度相同时略微优先内置工具，避免外部工具无条件抢占。
            if not tool_name.startswith("mcp__"):
                score += 0.05
            scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        ranked = [
            item
            for score, item in scored
            if score > 0
            and str(item.get("function", {}).get("name", ""))
            not in explicitly_named_names
        ]
        picked = (explicitly_named + ranked)[:max_tools]
        if picked:
            return picked
        return all_tools[:max_tools]


_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def _tokenize(text: str) -> set[str]:
    tokens = {token.lower() for token in _TOKEN_RE.findall(text or "")}
    cjk = "".join(char for char in (text or "") if "\u4e00" <= char <= "\u9fff")
    tokens.update(cjk)
    tokens.update(cjk[index:index + 2] for index in range(max(0, len(cjk) - 1)))
    return {token for token in tokens if token}

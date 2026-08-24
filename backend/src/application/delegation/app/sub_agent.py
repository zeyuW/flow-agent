"""SubAgent: async LLM tool loop for multi-step task execution (spec 4)."""

import asyncio
import json
import logging
import time
from typing import Any

from application.capabilities.tools.registry import ToolRegistry
from application.capabilities.tools.base import ToolResult
from application.capabilities.llm.client import llm_stage

logger = logging.getLogger(__name__)
_TOOL_RESULT_TRIM_N = 3000


class SubAgent:
    """Controlled LLM tool loop for delegated background tasks.

    Implements spec 4: run(task) -> iterate LLM calls with tools until completion,
    max_iterations safety limit, tool result trimming, completion detection.
    """

    def __init__(
        self,
        *,
        tools: list | None = None,
        tool_schemas: list[dict] | None = None,
        system_prompt: str = "",
        max_iterations: int = 30,
        llm_client: Any = None,
    ) -> None:
        self._tools = tools or []
        self._tool_schemas = tool_schemas or []
        self._system_prompt = system_prompt
        self._max_iterations = max_iterations
        self._llm = llm_client
        self._registry = ToolRegistry()
        for t in self._tools:
            self._registry.register(t)
        self.last_exit_reason: str = ""
        self.last_error: str = ""
        self.last_steps: int = 0

    async def run(self, task: str) -> str:
        """Execute the multi-step task (spec 4a)."""
        messages: list[dict] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": task},
        ]

        for iteration in range(self._max_iterations):
            self.last_steps = iteration + 1
            step_started = time.monotonic()
            # 4b: LLM call with tools
            with llm_stage("subagent"):
                response = self._llm.generate(
                    messages=messages,
                    tools=self._tool_schemas,
                ) if self._llm else None

            if response is None:
                self.last_exit_reason = "error"
                self.last_error = "no_llm_client"
                logger.info(
                    "[subagent] step=%d/%d elapsed=%.2fs result=error",
                    iteration + 1,
                    self._max_iterations,
                    time.monotonic() - step_started,
                )
                return "SubAgent: no LLM client configured"

            if getattr(response, "error", None):
                self.last_exit_reason = "error"
                self.last_error = str(response.error)
                logger.error(
                    "[subagent] LLM request failed: stage=%s error_type=%s status_code=%s",
                    getattr(response, "stage", "subagent"),
                    getattr(response, "error_type", ""),
                    getattr(response, "status_code", ""),
                )
                return (response.content or "").strip()

            logger.info(
                "[subagent] step=%d/%d elapsed=%.2fs tool_calls=%d",
                iteration + 1,
                self._max_iterations,
                time.monotonic() - step_started,
                len(response.tool_calls or []),
            )

            # 4c: Completion detection — no tool calls means finished
            if not response.tool_calls:
                self.last_exit_reason = "completed"
                logger.info("[subagent] completed in %d iterations", iteration + 1)
                return (response.content or "").strip()

            # 4d: Execute each tool call
            assistant_msg = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [],
            }
            tool_msgs = []

            for tc in response.tool_calls:
                args = tc.arguments if isinstance(tc.arguments, dict) else {}
                result = self._registry.execute(tc.name, args)
                assistant_msg["tool_calls"].append({
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(args, ensure_ascii=False),
                    },
                })
                trimmed = _trim(result.content, _TOOL_RESULT_TRIM_N)
                tool_msgs.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": trimmed,
                })

            # 4e: Append results to message history
            messages.append(assistant_msg)
            messages.extend(tool_msgs)

            # Trim old tool results to keep context manageable
            if len(messages) > 30:
                messages = _trim_old_tool_results(messages, keep_recent=20)

        # Max iterations reached
        self.last_exit_reason = "max_iterations"
        logger.warning("[subagent] max iterations (%d) reached", self._max_iterations)
        return "Tool call max iterations reached."


def _trim(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    return text[:n] + f"\n... (truncated {len(text) - n} chars)"


def _trim_old_tool_results(messages: list, keep_recent: int = 20) -> list:
    """Keep system prompt + recent N messages; compress older tool results."""
    if len(messages) <= keep_recent + 2:
        return messages
    head = messages[:2]
    start = max(2, len(messages) - keep_recent)
    # Never start with a tool result: it must follow its assistant tool call.
    while start < len(messages) and messages[start].get("role") == "tool":
        start += 1
    tail = messages[start:]
    return head + tail

"""SpawnTool: creates subagent background tasks (spec 1).

Implements spec 1a-1d: SpawnTool with DelegationPolicy check,
background spawn (1c) and sync spawn (1d).
"""

import asyncio
import json
import logging
from typing import Any

from flow_agent.core.delegation import DelegationPolicy
from flow_agent.subagent.models import SpawnDecision
from flow_agent.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


def _run_async(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=300)
        return loop.run_until_complete(coro)


class SpawnTool:
    """spawn tool: delegates a task to a background subagent (spec 1a).

    The main agent calls this to offload multi-step work. Supports both
    background mode (returns immediately) and sync mode (blocks for result).
    """

    def __init__(self, manager=None, policy: DelegationPolicy | None = None) -> None:
        self._manager = manager
        self._policy = policy or DelegationPolicy()

    @property
    def name(self) -> str:
        return "spawn"

    @property
    def description(self) -> str:
        return (
            "Create a background subagent to handle a complex multi-step task. "
            "Use for research, analysis, or code generation. "
            "The subagent works independently and returns results when done."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task description for the subagent",
                },
                "label": {
                    "type": "string",
                    "description": "Short label for this subagent task",
                },
                "profile": {
                    "type": "string",
                    "enum": ["research", "scripting", "general"],
                    "description": "Subagent capability profile",
                    "default": "research",
                },
                "run_in_background": {
                    "type": "boolean",
                    "description": "Run in background (return immediately) or sync (wait for result)",
                    "default": True,
                },
            },
            "required": ["task"],
        }

    def run(self, tool_input: dict[str, str]) -> ToolResult:
        try:
            if self._manager is None:
                return ToolResult(ok=False, content="spawn tool not configured (no subagent manager)")

            task = tool_input.get("task", "")
            label = tool_input.get("label") or task[:40]
            profile = tool_input.get("profile", "research")
            run_in_background = tool_input.get("run_in_background", True)
            if isinstance(run_in_background, str):
                run_in_background = run_in_background.lower() in ("true", "1", "yes")

            # 1b: Delegation policy check
            decision = self._policy.decide(
                user_input=task,
                tool_step_budget=10,
            )
            if decision.action == "reject":
                return ToolResult(ok=False, content=f"Spawn rejected: {decision.reason}")

            running_count = getattr(self._manager, 'running_count', 0)
            spawn_decision = SpawnDecision(
                allowed=decision.action in ("spawn_subagent", "background_job"),
                reason=decision.reason,
                profile=profile,
            )

            if run_in_background:
                # 1c: background mode
                result_text = _run_async(
                    self._manager.spawn(
                        task=task,
                        label=label,
                        profile=profile,
                        decision=spawn_decision,
                    )
                )
            else:
                # 1d: sync mode
                result_text = _run_async(
                    self._manager.spawn_sync(
                        task=task,
                        label=label,
                        profile=profile,
                    )
                )

            return ToolResult(ok=True, content=result_text)
        except Exception as exc:
            logger.exception("spawn tool failed")
            return ToolResult(ok=False, content=f"spawn failed: {exc}")

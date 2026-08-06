"""创建子代理后台任务的工具。"""

import asyncio
import logging
import threading
from typing import Any

from application.conversation.app.delegation import DelegationPolicy
from application.delegation.app.models import SpawnDecision
from application.capabilities.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


def _run_async(coro):
    """在同步工具边界执行协程，兼容当前线程已有事件循环的场景。"""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result = []
    errors = []

    def run_in_thread() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run_in_thread, name="spawn-tool-sync")
    thread.start()
    thread.join(timeout=300)
    if thread.is_alive():
        raise TimeoutError("spawn execution timed out")
    if errors:
        raise errors[0]
    return result[0]


class SpawnTool:
    """把复杂任务委派给子代理，支持后台执行和同步等待。"""

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

            origin_channel = tool_input.get("__channel", "cli")
            origin_chat_id = tool_input.get("__chat_id", "default")
            origin_session_id = tool_input.get("__session_id", origin_chat_id)

            # 委派策略仍在工具边界执行，避免无意义地创建子代理。
            decision = self._policy.decide(
                user_input=task,
                tool_step_budget=10,
            )
            if decision.action == "reject":
                return ToolResult(ok=False, content=f"Spawn rejected: {decision.reason}")

            spawn_decision = SpawnDecision(
                allowed=decision.action in ("spawn_subagent", "background_job"),
                reason=decision.reason,
                profile=profile,
            )

            if hasattr(self._manager, "run_spawn_threadsafe"):
                result_text = self._manager.run_spawn_threadsafe(
                    run_in_background=run_in_background,
                    task=task,
                    label=label,
                    profile=profile,
                    origin_channel=origin_channel,
                    origin_chat_id=origin_chat_id,
                    origin_session_id=origin_session_id,
                    decision=spawn_decision,
                )
            elif run_in_background:
                result_text = _run_async(
                    self._manager.spawn(
                        task=task,
                        label=label,
                        profile=profile,
                        origin_channel=origin_channel,
                        origin_chat_id=origin_chat_id,
                        origin_session_id=origin_session_id,
                        decision=spawn_decision,
                    )
                )
            else:
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

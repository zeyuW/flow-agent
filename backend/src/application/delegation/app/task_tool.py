"""Lead Agent 委派 Subagent 的同步工具。"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from application.capabilities.tools.base import ToolResult
from application.delegation.app.models import SubagentResult

logger = logging.getLogger(__name__)


class TaskTool:
    """以工具形式执行一次隔离 Subagent 任务。"""

    @property
    def name(self) -> str:
        return "task"

    @property
    def description(self) -> str:
        return (
            "Delegate a bounded task to an isolated subagent. "
            "Use the result to continue reasoning and answer the user. "
            "If multiple tasks are used, retry only failed tasks; do not rerun completed tasks."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "The bounded task for the subagent",
                },
                "profile": {
                    "type": "string",
                    "enum": ["research", "general", "scripting"],
                    "description": "The subagent capability profile",
                    "default": "research",
                },
                "context": {
                    "type": "string",
                    "description": "Optional context explicitly shared with the subagent",
                },
                "max_turns": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 10,
                },
                "timeout": {
                    "type": "number",
                    "minimum": 1,
                    "maximum": 1800,
                    "default": 300,
                },
            },
            "required": ["description"],
        }

    def __init__(self, manager=None) -> None:
        self._manager = manager

    def run(self, tool_input: dict[str, Any]) -> ToolResult:
        task_id = uuid4().hex[:12]
        description = str(tool_input.get("description", "")).strip()
        if not description:
            return ToolResult(ok=False, content="task failed: description 不能为空")
        if self._manager is None:
            return ToolResult(ok=False, content="task failed: subagent manager 未配置")

        try:
            result = self._manager.run_task_threadsafe(
                task_id=task_id,
                description=description,
                profile=str(tool_input.get("profile", "research")),
                context=str(tool_input.get("context", "")),
                max_turns=int(tool_input.get("max_turns", 10)),
                timeout=float(tool_input.get("timeout", 300)),
                run_id=str(tool_input.get("__trace_id", "default")),
            )
            if not isinstance(result, SubagentResult):
                raise TypeError("subagent manager 返回了无效结果")
            return ToolResult(
                ok=result.status == "completed",
                content=json.dumps(result.to_dict(), ensure_ascii=False),
            )
        except Exception as exc:
            logger.exception("task tool failed: task_id=%s", task_id)
            failed = SubagentResult(
                task_id=task_id,
                status="failed",
                error=str(exc),
            )
            return ToolResult(
                ok=False,
                content=json.dumps(failed.to_dict(), ensure_ascii=False),
            )

    async def run_async(self, tool_input: dict[str, Any]) -> ToolResult:
        """异步执行 task，供主 Agent 并行委派使用。"""

        task_id = uuid4().hex[:12]
        description = str(tool_input.get("description", "")).strip()
        if not description:
            return ToolResult(ok=False, content="task failed: description 不能为空")
        if self._manager is None:
            return ToolResult(ok=False, content="task failed: subagent manager 未配置")

        try:
            runner = getattr(self._manager, "run_task_async", None)
            if not callable(runner):
                return self.run(tool_input)
            result = await runner(
                task_id=task_id,
                description=description,
                profile=str(tool_input.get("profile", "research")),
                context=str(tool_input.get("context", "")),
                max_turns=int(tool_input.get("max_turns", 10)),
                timeout=float(tool_input.get("timeout", 300)),
                run_id=str(tool_input.get("__trace_id", "default")),
            )
            if not isinstance(result, SubagentResult):
                raise TypeError("subagent manager 返回了无效结果")
            return ToolResult(
                ok=result.status == "completed",
                content=json.dumps(result.to_dict(), ensure_ascii=False),
            )
        except Exception as exc:
            logger.exception("async task tool failed: task_id=%s", task_id)
            failed = SubagentResult(
                task_id=task_id,
                status="failed",
                error=str(exc),
            )
            return ToolResult(
                ok=False,
                content=json.dumps(failed.to_dict(), ensure_ascii=False),
            )

"""自动化作业的 Agent 工具适配器。

这些类负责把自动化运行时暴露给 Agent 工具系统，自动化业务本身不依赖它们。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from difflib import get_close_matches
from typing import Any

from application.automation.app.runtime import AutomationRuntime
from application.capabilities.tools.base import ToolResult


@dataclass(slots=True)
class RunAutomationJobTool:
    """把已注册任务提交到后台线程执行。"""

    runtime: AutomationRuntime

    @property
    def name(self) -> str:
        return "run_automation_job"

    @property
    def description(self) -> str:
        return "异步执行一个已注册的后台任务，立即返回提交结果"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "job_name": {
                    "type": "string",
                    "description": "后台任务名称；插件任务格式为 插件名:任务名",
                }
            },
            "required": ["job_name"],
        }

    def run(self, tool_input: dict[str, Any]) -> ToolResult:
        name = str(tool_input.get("job_name", "")).strip().replace("：", ":")
        if self.runtime.registry.get(name) is None:
            available = self.runtime.registry.list_names()
            suggestions = get_close_matches(name, available, n=3, cutoff=0.55)
            return ToolResult(
                ok=False,
                content=json.dumps(
                    {
                        "error": "unknown_automation_job",
                        "requested": name,
                        "suggestions": suggestions,
                        "available_jobs": available,
                    },
                    ensure_ascii=False,
                ),
            )
        try:
            self.runtime.run_job_async(name)
        except Exception as exc:
            return ToolResult(ok=False, content=f"后台任务提交失败: {exc}")
        return ToolResult(ok=True, content=f"后台任务已提交: {name}")


@dataclass(slots=True)
class ListAutomationJobsTool:
    """列出当前插件代际注册的后台任务。"""

    runtime: AutomationRuntime

    @property
    def name(self) -> str:
        return "list_automation_jobs"

    @property
    def description(self) -> str:
        return "列出当前可执行的后台任务名称"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def run(self, tool_input: dict[str, Any]) -> ToolResult:
        del tool_input
        return ToolResult(
            ok=True,
            content=json.dumps(
                {"jobs": self.runtime.registry.list_names()},
                ensure_ascii=False,
            ),
        )


@dataclass(slots=True)
class ListAutomationRunsTool:
    """查询持久化后台任务运行历史。"""

    runtime: AutomationRuntime

    @property
    def name(self) -> str:
        return "list_automation_runs"

    @property
    def description(self) -> str:
        return "查询最近的后台任务状态、结果和错误"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20,
                }
            },
        }

    def run(self, tool_input: dict[str, Any]) -> ToolResult:
        limit = max(1, min(100, int(tool_input.get("limit", 20))))
        try:
            runs = self.runtime.store.list_runs(limit=limit)
        except TypeError:
            runs = self.runtime.store.list_runs()[-limit:]
        return ToolResult(
            ok=True,
            content=json.dumps(
                {
                    "runs": [
                        {
                            "run_id": run.run_id,
                            "job_name": run.job_name,
                            "status": run.status,
                            "attempts": run.attempts,
                            "result": run.result,
                            "error": run.error,
                            "error_category": run.error_category,
                            "started_at": run.started_at.isoformat(),
                            "finished_at": (
                                run.finished_at.isoformat()
                                if run.finished_at is not None
                                else None
                            ),
                        }
                        for run in runs
                    ]
                },
                ensure_ascii=False,
            ),
        )


__all__ = [
    "ListAutomationJobsTool",
    "ListAutomationRunsTool",
    "RunAutomationJobTool",
]

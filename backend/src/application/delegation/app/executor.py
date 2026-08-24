"""执行隔离的 Subagent 任务并转换为稳定结果。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from application.delegation.app.models import SubagentResult
from application.delegation.app.profiles import build_spawn_spec

_DEFAULT_MAX_TURNS = 10
_DEFAULT_TIMEOUT_SECONDS = 300.0
_MAX_RESULT_CHARS = 12_000


class SubagentExecutor:
    """负责一次 Subagent 执行，不管理会话通知或持久化。"""

    def __init__(
        self,
        *,
        runtime: Any,
        spec_builder: Callable[..., Any] = build_spawn_spec,
    ) -> None:
        self._runtime = runtime
        self._spec_builder = spec_builder

    async def execute(
        self,
        *,
        task_id: str,
        description: str,
        profile: str = "research",
        context: str = "",
        max_turns: int = _DEFAULT_MAX_TURNS,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> SubagentResult:
        """执行一个隔离任务并返回结构化结果。"""

        prompt = _build_prompt(description, context)
        try:
            spec = self._spec_builder(
                profile=profile,
                max_iterations=max(1, int(max_turns)),
            )
            agent = spec.build(runtime=self._runtime)
            summary = await asyncio.wait_for(
                agent.run(prompt), timeout=max(1.0, float(timeout))
            )
            exit_reason = getattr(agent, "last_exit_reason", "completed")
            steps = getattr(agent, "last_steps", 0)
            status = "completed" if exit_reason == "completed" else "failed"
            return SubagentResult(
                task_id=task_id,
                status=status,
                summary=_trim(str(summary or "")),
                error=(
                    None
                    if status == "completed"
                    else str(getattr(agent, "last_error", "") or exit_reason)
                ),
                steps=steps,
            )
        except asyncio.TimeoutError:
            return SubagentResult(
                task_id=task_id,
                status="timed_out",
                error="subagent_timeout",
            )
        except Exception as exc:
            return SubagentResult(
                task_id=task_id,
                status="failed",
                error=str(exc),
            )


def _build_prompt(description: str, context: str) -> str:
    description = description.strip()
    context = context.strip()
    if not context:
        return f"目标：{description}"
    return f"目标：{description}\n上下文：{context}"


def _trim(value: str) -> str:
    if len(value) <= _MAX_RESULT_CHARS:
        return value
    return value[:_MAX_RESULT_CHARS] + "\n...（结果已截断）"

"""AgentBackgroundJobRunner: lifecycle wrapper for SubAgent execution (spec 3)."""

import logging
from typing import Any, Callable

from flow_agent.subagent.models import AgentBackgroundJobSpec, JobRunResult

logger = logging.getLogger(__name__)


class AgentBackgroundJobRunner:
    """Wraps a SubAgent factory with lifecycle management (spec 3b-3d).

    Handles: agent construction, run(), exception capture, status normalization.
    """

    def __init__(self, agent_factory: Callable[[], Any]) -> None:
        self._agent_factory = agent_factory

    async def run(self, spec: AgentBackgroundJobSpec) -> JobRunResult:
        """Execute the subagent job and return standardized result (spec 3c)."""
        try:
            agent = self._agent_factory()
            result_summary = await agent.run(spec.task)
            exit_reason = getattr(agent, "last_exit_reason", "completed")
            status = "completed" if exit_reason == "completed" else "failed"
            return JobRunResult(
                job_id=spec.job_id,
                status=status,
                exit_reason=exit_reason,
                result_summary=result_summary,
            )
        except Exception as exc:
            logger.exception("[spawn] subagent failed job_id=%s", spec.job_id)
            return JobRunResult(
                job_id=spec.job_id,
                status="error",
                exit_reason="error",
                result_summary="",
                error=str(exc),
            )

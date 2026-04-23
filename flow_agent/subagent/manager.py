import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from flow_agent.dashboard.store import InMemoryDashboardStore
from flow_agent.guard.guards import SubagentConcurrencyGuard
from flow_agent.subagent.models import SubagentTask
from flow_agent.subagent.completion import CompletionFlow
from flow_agent.subagent.profiles import SubagentRouter, SubagentProfile


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SubagentManager:
    """Manage subagent tasks lifecycle and persistence."""

    tasks_path: Path
    dashboard: InMemoryDashboardStore | None = None
    concurrency_guard: SubagentConcurrencyGuard = field(
        default_factory=lambda: SubagentConcurrencyGuard(max_concurrency=2)
    )
    completion_flow: CompletionFlow = field(default_factory=CompletionFlow)
    router: SubagentRouter = field(
        default_factory=lambda: SubagentRouter(
            profiles=[
                SubagentProfile(name="general", task_types=("general", "analysis", "file_ops")),
                SubagentProfile(name="code", task_types=("code", "refactor", "test")),
            ]
        )
    )

    def create_task(
        self,
        kind: str,
        payload: dict[str, object],
        *,
        parent_trace_id: str | None = None,
    ) -> SubagentTask:
        task = SubagentTask(
            task_id=uuid4().hex[:12],
            kind=kind,
            payload=payload,
            parent_trace_id=parent_trace_id,
        )
        self._persist(task)
        profile = self.router.route(kind)
        self._record(
            {
                "type": "subagent_task_created",
                "task_id": task.task_id,
                "kind": kind,
                "profile": profile.name if profile else "none",
                "parent_trace_id": parent_trace_id,
            }
        )
        return task

    def run_task(
        self,
        task: SubagentTask,
        executor,
    ) -> None:
        """Run a task in background thread."""

        def _run() -> None:
            decision = self.concurrency_guard.acquire()
            if not decision.allowed:
                task.status = "failed"
                task.error = decision.reason
                task.finished_at = _utc_now()
                self._persist(task)
                self._record(
                    {
                        "type": "subagent_task_finished",
                        "task_id": task.task_id,
                        "kind": task.kind,
                        "status": task.status,
                        "parent_trace_id": task.parent_trace_id,
                    }
                )
                return
            task.status = "running"
            task.started_at = _utc_now()
            self._persist(task)
            self._record({"type": "subagent_task_started", "task_id": task.task_id, "kind": task.kind})
            try:
                result = executor(task)
                task.status = "completed"
                task.result = result
                task.error = None
            except Exception as exc:
                logger.exception("subagent task failed id=%s", task.task_id)
                task.status = "failed"
                task.error = str(exc)
            finally:
                task.finished_at = _utc_now()
                self._persist(task)
                self._record(
                    {
                        "type": "subagent_task_finished",
                        "task_id": task.task_id,
                        "kind": task.kind,
                        "status": task.status,
                        "parent_trace_id": task.parent_trace_id,
                    }
                )
                summary = self.completion_flow.summarize(task)
                self._record(
                    {
                        "type": "subagent_completion",
                        "task_id": summary.task_id,
                        "status": summary.status,
                        "summary": summary.summary,
                        "parent_trace_id": task.parent_trace_id,
                    }
                )
                self.concurrency_guard.release()

        threading.Thread(target=_run, daemon=True).start()

    def _persist(self, task: SubagentTask) -> None:
        try:
            self.tasks_path.parent.mkdir(parents=True, exist_ok=True)
            with self.tasks_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(_task_to_dict(task), ensure_ascii=False) + "\n")
        except Exception:
            logger.exception("failed persisting subagent task")

    def _record(self, event: dict[str, object]) -> None:
        if self.dashboard is None:
            return
        try:
            self.dashboard.record(event)
        except Exception:
            logger.exception("dashboard record subagent failed")

    def list_recent_tasks(self, limit: int = 10) -> list[dict[str, object]]:
        if not self.tasks_path.exists():
            return []
        lines = self.tasks_path.read_text(encoding="utf-8").splitlines()
        rows: list[dict[str, object]] = []
        for line in lines[-max(1, limit):]:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows


def _task_to_dict(task: SubagentTask) -> dict[str, object]:
    return {
        "task_id": task.task_id,
        "kind": task.kind,
        "payload": task.payload,
        "parent_trace_id": task.parent_trace_id,
        "status": task.status,
        "created_at": task.created_at.isoformat(),
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "result": task.result,
        "error": task.error,
    }


def _utc_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


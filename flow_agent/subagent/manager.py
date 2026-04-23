import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from flow_agent.dashboard.store import InMemoryDashboardStore
from flow_agent.guard.guards import SubagentConcurrencyGuard
from flow_agent.subagent.models import SubagentTask


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SubagentManager:
    """Manage subagent tasks lifecycle and persistence."""

    tasks_path: Path
    dashboard: InMemoryDashboardStore | None = None
    concurrency_guard: SubagentConcurrencyGuard = field(
        default_factory=lambda: SubagentConcurrencyGuard(max_concurrency=2)
    )

    def create_task(self, kind: str, payload: dict[str, object]) -> SubagentTask:
        task = SubagentTask(task_id=uuid4().hex[:12], kind=kind, payload=payload)
        self._persist(task)
        self._record({"type": "subagent_task_created", "task_id": task.task_id, "kind": kind})
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


def _task_to_dict(task: SubagentTask) -> dict[str, object]:
    return {
        "task_id": task.task_id,
        "kind": task.kind,
        "payload": task.payload,
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


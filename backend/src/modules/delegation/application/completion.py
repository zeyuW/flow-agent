from dataclasses import dataclass

from modules.delegation.application.models import SubagentTask


@dataclass(slots=True)
class CompletionSummary:
    task_id: str
    status: str
    summary: str


class CompletionFlow:
    """Standardize subagent completion and summary."""

    def summarize(self, task: SubagentTask) -> CompletionSummary:
        if task.status == "completed":
            summary = f"task {task.task_id} completed"
        elif task.status == "failed":
            summary = f"task {task.task_id} failed: {task.error or 'unknown'}"
        else:
            summary = f"task {task.task_id} status={task.status}"
        return CompletionSummary(task_id=task.task_id, status=task.status, summary=summary)


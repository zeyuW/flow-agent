from dataclasses import dataclass
from pathlib import Path

from flow_agent.dashboard.store import InMemoryDashboardStore
from flow_agent.subagent.manager import SubagentManager


@dataclass(slots=True)
class SubagentRuntime:
    """Container for subagent manager and resources."""

    manager: SubagentManager


def create_subagent_runtime(data_dir: Path, dashboard: InMemoryDashboardStore | None = None) -> SubagentRuntime:
    manager = SubagentManager(tasks_path=data_dir / "subagent_tasks.jsonl", dashboard=dashboard)
    return SubagentRuntime(manager=manager)


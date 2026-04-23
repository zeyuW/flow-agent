from dataclasses import dataclass

from flow_agent.subagent.runtime import SubagentRuntime


@dataclass(slots=True)
class SubagentFacade:
    runtime: SubagentRuntime

    def recent_tasks(self, limit: int = 10) -> list[dict[str, object]]:
        return self.runtime.manager.list_recent_tasks(limit=limit)

from dataclasses import dataclass

from flow_agent.background.jobs import JobSpec
from flow_agent.background.runtime import InMemoryJobRegistry
from flow_agent.memory.consolidation import MemoryConsolidator


@dataclass(slots=True)
class ConsolidationWorker:
    """Register periodic consolidation jobs into background runtime."""

    consolidator: MemoryConsolidator
    session_id: str = "default"

    def register(self, registry: InMemoryJobRegistry) -> None:
        def _job() -> None:
            self.consolidator.consolidate(self.session_id)

        registry.register(JobSpec(name="memory_consolidation", func=_job, max_retries=1))


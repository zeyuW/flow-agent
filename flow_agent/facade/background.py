from dataclasses import dataclass

from flow_agent.background.runtime import BackgroundRuntime
from flow_agent.background.store import JobRun


@dataclass(slots=True)
class BackgroundFacade:
    """Facade for background runtime operations."""

    runtime: BackgroundRuntime

    def run_job(self, name: str) -> JobRun:
        return self.runtime.run_job(name)

    def run_job_async(self, name: str) -> None:
        self.runtime.run_job_async(name)


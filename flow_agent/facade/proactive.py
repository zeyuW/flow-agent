from dataclasses import dataclass

from flow_agent.proactive.runtime import ProactiveRuntime
from flow_agent.proactive.types import ProactiveTickResult


@dataclass(slots=True)
class ProactiveFacade:
    """Facade for proactive runtime operations."""

    runtime: ProactiveRuntime

    def tick(self) -> ProactiveTickResult:
        return self.runtime.tick_runner.tick()

    def start(self) -> None:
        self.runtime.scheduler.start()

    def stop(self) -> None:
        self.runtime.scheduler.stop()


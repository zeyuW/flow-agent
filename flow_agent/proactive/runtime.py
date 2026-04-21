from dataclasses import dataclass

from flow_agent.proactive.scheduler import IntervalScheduler
from flow_agent.proactive.tick import ProactiveTickRunner


@dataclass(slots=True)
class ProactiveRuntime:
    scheduler: IntervalScheduler
    tick_runner: ProactiveTickRunner


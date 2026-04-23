from flow_agent.core.agent import Agent
from flow_agent.core.models import AgentResponse
from flow_agent.core.pipeline import TurnPipeline
from flow_agent.infra.trace import TraceRecorder
from flow_agent.memory.organizer import MemoryOrganizer
from flow_agent.memory.retriever import MemoryRetriever
from flow_agent.tools.registry import ToolRegistry
from flow_agent.dashboard.store import InMemoryDashboardStore


class Orchestrator:
    def __init__(
        self,
        agent: Agent,
        tool_registry: ToolRegistry,
        max_tool_steps: int = 5,
        retriever: MemoryRetriever | None = None,
        retrieval_max_items: int = 6,
        recorder: TraceRecorder | None = None,
        organizer: MemoryOrganizer | None = None,
        dashboard: InMemoryDashboardStore | None = None,
    ) -> None:
        self.pipeline = TurnPipeline(
            agent=agent,
            tool_registry=tool_registry,
            max_tool_steps=max_tool_steps,
            retriever=retriever,
            retrieval_max_items=retrieval_max_items,
            recorder=recorder,
            organizer=organizer,
            dashboard=dashboard,
        )

    def run_turn(self, user_input: str, session_id: str = "default") -> AgentResponse:
        return self.pipeline.process_turn(user_input=user_input, session_id=session_id)

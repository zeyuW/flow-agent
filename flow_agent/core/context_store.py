from dataclasses import dataclass, field
from typing import Any

from flow_agent.core.agent import Agent
from flow_agent.memory.models import RetrievedMemory
from flow_agent.memory.retriever import MemoryRetriever


@dataclass(slots=True)
class PreparedBundle:
    history: list[dict[str, str]]
    retrieved: list[RetrievedMemory] = field(default_factory=list)
    retrieval_trace: list[dict[str, str]] = field(default_factory=list)
    persona_block: str = ""
    channel_metadata: dict[str, Any] = field(default_factory=dict)
    skill_mentions: list[str] = field(default_factory=list)


class ContextStore:
    """Prepare/commit wrappers around context + retriever."""

    def __init__(
        self,
        agent: Agent,
        retriever: MemoryRetriever | None = None,
        retrieval_max_items: int = 6,
    ) -> None:
        self.agent = agent
        self.retriever = retriever
        self.retrieval_max_items = retrieval_max_items

    def prepare(
        self,
        *,
        session_id: str,
        user_input: str,
        channel_metadata: dict[str, Any] | None = None,
        persona_block: str = "",
    ) -> PreparedBundle:
        history = self.agent.context.get_history(session_id)
        retrieved: list[RetrievedMemory] = []
        trace: list[dict[str, str]] = []
        if self.retriever is not None and self.retrieval_max_items > 0:
            retrieved = self.retriever.retrieve(
                session_id=session_id,
                query=user_input,
                max_items=self.retrieval_max_items,
            )
            trace.append({"items": str(len(retrieved)), "max_items": str(self.retrieval_max_items)})
        return PreparedBundle(
            history=history,
            retrieved=retrieved,
            retrieval_trace=trace,
            persona_block=persona_block,
            channel_metadata=channel_metadata or {},
            skill_mentions=[],
        )

    def commit(self, *, user_input: str, assistant_output: str) -> None:
        self.agent.commit_turn(user_input=user_input, assistant_output=assistant_output)


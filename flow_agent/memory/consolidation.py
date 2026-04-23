from dataclasses import dataclass

from flow_agent.memory.organizer import SimpleMemoryOrganizer
from flow_agent.memory.profile_extractor import ProfileExtractor
from flow_agent.memory.store import MessageStore


@dataclass(slots=True)
class ConsolidationResult:
    before: int
    after: int
    extracted_profile_items: int


class MemoryConsolidator:
    """Background consolidation: organize + profile extraction summary."""

    def __init__(self, store: MessageStore, *, max_messages: int = 200, dedupe: bool = True) -> None:
        self.organizer = SimpleMemoryOrganizer(store=store, max_messages=max_messages, dedupe=dedupe)
        self.store = store
        self.extractor = ProfileExtractor()

    def consolidate(self, session_id: str) -> ConsolidationResult:
        stats = self.organizer.organize(session_id)
        history = self.store.list_messages(session_id)
        profile = self.extractor.extract(history)
        profile_count = sum(
            len(x)
            for x in [
                profile.identity,
                profile.preference,
                profile.goal,
                profile.constraint,
                profile.milestone,
                profile.routine,
            ]
        )
        return ConsolidationResult(
            before=stats["before"],
            after=stats["after"],
            extracted_profile_items=profile_count,
        )


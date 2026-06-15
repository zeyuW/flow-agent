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
        self.min_messages_to_run = 20
        self.max_queue_pressure = 0.8

    def should_consolidate(
        self,
        session_id: str,
        *,
        queue_pressure: float = 0.0,
        force: bool = False,
    ) -> bool:
        if force:
            return True
        if queue_pressure > self.max_queue_pressure:
            return False
        history = self.store.list_messages(session_id)
        return len(history) >= self.min_messages_to_run

    def consolidate(
        self,
        session_id: str,
        *,
        queue_pressure: float = 0.0,
        force: bool = False,
    ) -> ConsolidationResult:
        if not self.should_consolidate(session_id, queue_pressure=queue_pressure, force=force):
            history = self.store.list_messages(session_id)
            return ConsolidationResult(
                before=len(history),
                after=len(history),
                extracted_profile_items=0,
            )
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


from pathlib import Path

from flow_agent.proactive.pipeline import (
    CandidateRanker,
    DecisionLayer,
    DriftRunner,
    PreGate,
    ProactiveTickRunner,
    SourceGateway,
)
from flow_agent.proactive.sources import LocalFileSource
from flow_agent.proactive.store import SQLiteProactiveSentStore


def test_proactive_tick_send_and_dedup(tmp_path: Path):
    source_file = tmp_path / "proactive_items.txt"
    source_file.write_text("follow up with user\n", encoding="utf-8")
    db_path = tmp_path / "memory.db"

    sent_store = SQLiteProactiveSentStore(db_path=db_path)
    gate = PreGate(sent_store=sent_store, cooldown_seconds=0)
    source = LocalFileSource(source_file)
    runner = ProactiveTickRunner(
        gate=gate,
        gateway=SourceGateway([source]),
        ranker=CandidateRanker(),
        decision_layer=DecisionLayer(min_priority_to_send=0.0),
        drift_runner=DriftRunner(tmp_path / "tasks.txt"),
        sent_store=sent_store,
        dedup_ttl_seconds=3600,
    )

    first = runner.tick()
    second = runner.tick()

    assert first.sent is True
    assert first.reason == "sent"
    assert second.sent is False
    assert second.reason == "dedup_hit"


def test_proactive_tick_dispatcher_called(tmp_path: Path):
    source_file = tmp_path / "proactive_items.txt"
    source_file.write_text("ping qq now\n", encoding="utf-8")
    db_path = tmp_path / "memory.db"
    sent_store = SQLiteProactiveSentStore(db_path=db_path)
    gate = PreGate(sent_store=sent_store, cooldown_seconds=0)
    source = LocalFileSource(source_file)
    captured: list[str] = []

    class _Dispatcher:
        def dispatch(self, candidate) -> None:
            captured.append(candidate.content)

    runner = ProactiveTickRunner(
        gate=gate,
        gateway=SourceGateway([source]),
        ranker=CandidateRanker(),
        decision_layer=DecisionLayer(min_priority_to_send=0.0),
        drift_runner=DriftRunner(tmp_path / "tasks.txt"),
        sent_store=sent_store,
        dedup_ttl_seconds=3600,
        dispatcher=_Dispatcher(),
    )
    result = runner.tick()
    assert result.sent is True
    assert len(captured) == 1
    assert "ping qq now" in captured[0]


def test_proactive_tick_runs_drift_when_no_candidate(tmp_path: Path):
    db_path = tmp_path / "memory.db"
    tasks_file = tmp_path / "tasks.txt"
    tasks_file.write_text("light-check\n", encoding="utf-8")

    sent_store = SQLiteProactiveSentStore(db_path=db_path)
    gate = PreGate(sent_store=sent_store, cooldown_seconds=0)
    empty_source = LocalFileSource(tmp_path / "missing.txt")
    runner = ProactiveTickRunner(
        gate=gate,
        gateway=SourceGateway([empty_source]),
        ranker=CandidateRanker(),
        decision_layer=DecisionLayer(min_priority_to_send=0.0),
        drift_runner=DriftRunner(tasks_file),
        sent_store=sent_store,
        dedup_ttl_seconds=3600,
    )

    result = runner.tick()
    assert result.sent is False
    assert result.reason == "no_candidate:plan:readonly_task:light-check"


def test_candidate_ranker_feedback_boosts_sent_source():
    from flow_agent.proactive.pipeline import CandidateRanker
    from flow_agent.proactive.types import ProactiveCandidate

    ranker = CandidateRanker()
    c1 = ProactiveCandidate(key="a", content="A", source="s1", priority=0.5)
    c2 = ProactiveCandidate(key="b", content="B", source="s2", priority=0.5)
    first = ranker.rank([c1, c2])[0]
    assert first.key in {"a", "b"}
    ranker.mark_feedback("s2", sent=True)
    second = ranker.rank([c1, c2])[0]
    assert second.source == "s2"

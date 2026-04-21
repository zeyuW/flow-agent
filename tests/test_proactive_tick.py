from pathlib import Path

from flow_agent.proactive.gate import SimplePreGate
from flow_agent.proactive.source import LocalFileCandidateSource
from flow_agent.proactive.store import SQLiteProactiveSentStore
from flow_agent.proactive.tick import ProactiveTickRunner


def test_proactive_tick_send_and_dedup(tmp_path: Path):
    source_file = tmp_path / "proactive_items.txt"
    source_file.write_text("follow up with user\n", encoding="utf-8")
    db_path = tmp_path / "memory.db"

    sent_store = SQLiteProactiveSentStore(db_path=db_path)
    gate = SimplePreGate(sent_store=sent_store, cooldown_seconds=0)
    source = LocalFileCandidateSource(source_file)
    runner = ProactiveTickRunner(
        gate=gate,
        source=source,
        sent_store=sent_store,
        dedup_ttl_seconds=3600,
    )

    first = runner.tick()
    second = runner.tick()

    assert first.sent is True
    assert first.reason == "sent"
    assert second.sent is False
    assert second.reason == "dedup_hit"

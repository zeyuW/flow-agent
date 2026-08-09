"""记忆模块的 DDD 分层边界。"""

from __future__ import annotations

from pathlib import Path

MEMORY_ROOT = Path(__file__).parents[2] / "src" / "application" / "memory"


def test_memory_storage_and_query_services_are_in_their_layers() -> None:
    assert (MEMORY_ROOT / "infra" / "markdown_store.py").exists()
    assert (MEMORY_ROOT / "app" / "engine.py").exists()
    assert not (MEMORY_ROOT / "markdown_store.py").exists()
    assert not (MEMORY_ROOT / "memory_engine.py").exists()


def test_memory_domain_owns_shared_memory_records() -> None:
    domain_source = (MEMORY_ROOT / "domain" / "models.py").read_text(encoding="utf-8")
    vector_source = (MEMORY_ROOT / "infra" / "vector_store.py").read_text(
        encoding="utf-8"
    )
    retriever_source = (MEMORY_ROOT / "infra" / "retriever.py").read_text(
        encoding="utf-8"
    )
    assert "class MemoryItem" in domain_source
    assert "class RetrievalHit" in domain_source
    assert "class MemoryItem" not in vector_source
    assert "class RetrievalHit" not in retriever_source


def test_memory_dedup_service_is_not_in_domain() -> None:
    assert (MEMORY_ROOT / "app" / "dedup.py").exists()
    assert not (MEMORY_ROOT / "domain" / "dedup_decider.py").exists()


def test_memory_domain_has_no_infrastructure_dependency() -> None:
    source = (MEMORY_ROOT / "domain" / "models.py").read_text(encoding="utf-8")
    assert "application.memory.app" not in source
    assert "application.memory.infra" not in source
    assert "import sqlite3" not in source


def test_shared_consumers_depend_on_memory_ports_not_infrastructure() -> None:
    ports = MEMORY_ROOT / "ports.py"
    passive_prompt = MEMORY_ROOT.parent / "passive" / "app" / "prompt.py"
    passive_pipeline = MEMORY_ROOT.parent / "passive" / "app" / "pipeline.py"
    proactive_judge = MEMORY_ROOT.parent / "proactive" / "app" / "judge_loop.py"

    assert ports.exists()
    port_source = ports.read_text(encoding="utf-8")
    assert "class MemoryPromptStore(Protocol)" in port_source
    assert "class MemoryQueryService(Protocol)" in port_source

    for consumer in (passive_prompt, passive_pipeline, proactive_judge):
        source = consumer.read_text(encoding="utf-8")
        assert "application.memory.infra" not in source
        assert "application.memory.ports" in source

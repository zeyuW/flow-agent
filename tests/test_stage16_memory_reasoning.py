import time
from pathlib import Path

from flow_agent.background.consolidation_worker import ConsolidationWorker
from flow_agent.background.runtime import InMemoryJobRegistry
from flow_agent.memory.consolidation import MemoryConsolidator
from flow_agent.memory.profile_extractor import ProfileExtractor
from flow_agent.memory.query_builder import RetrievalQueryBuilder
from flow_agent.memory.query_rewriter import QueryRewriter
from flow_agent.memory.retriever import KeywordMemoryRetriever
from flow_agent.memory.store import InMemoryMessageStore
from flow_agent.proactive.judge import ProactiveJudge
from flow_agent.proactive.types import ProactiveCandidate
from flow_agent.subagent.manager import SubagentManager


def test_query_rewrite_and_plan():
    rw = QueryRewriter().rewrite("我叫什么名字")
    plan = RetrievalQueryBuilder().build(rw, max_items=5)
    assert rw.intent in {"identity", "general"}
    assert plan.max_items == 5
    assert isinstance(plan.query, str)


def test_retriever_uses_rewrite_path():
    store = InMemoryMessageStore()
    store.append_message("s1", "user", "我叫测试用户")
    r = KeywordMemoryRetriever(store=store)
    got = r.retrieve("s1", "我叫什么", 3)
    assert len(got) >= 1


def test_profile_extractor_and_consolidator():
    store = InMemoryMessageStore()
    store.append_message("s1", "user", "我叫小明")
    store.append_message("s1", "user", "我喜欢跑步")
    profile = ProfileExtractor().extract(store.list_messages("s1"))
    assert len(profile.identity) >= 1
    assert len(profile.preference) >= 1
    result = MemoryConsolidator(store=store).consolidate("s1")
    assert result.after <= result.before


def test_consolidation_worker_registers_job():
    store = InMemoryMessageStore()
    reg = InMemoryJobRegistry()
    worker = ConsolidationWorker(consolidator=MemoryConsolidator(store=store), session_id="s1")
    worker.register(reg)
    assert reg.get("memory_consolidation") is not None


def test_proactive_judge_decision():
    judge = ProactiveJudge()
    send = judge.decide(ProactiveCandidate(key="a", content="这是一个可发送的跟进提醒消息", priority=0.9))
    skip = judge.decide(ProactiveCandidate(key="b", content="短", priority=0.9))
    assert send.action in {"send", "defer"}
    assert skip.action in {"skip", "defer"}


def test_subagent_parent_child_trace_and_poll(tmp_path: Path):
    mgr = SubagentManager(tasks_path=tmp_path / "tasks.jsonl")
    task = mgr.create_task("code", {"x": 1}, parent_trace_id="trace-parent-1")
    mgr.run_task(task, executor=lambda t: {"ok": True, "kind": t.kind})
    time.sleep(0.05)
    rows = mgr.list_recent_tasks(limit=5)
    assert any(row.get("parent_trace_id") == "trace-parent-1" for row in rows)


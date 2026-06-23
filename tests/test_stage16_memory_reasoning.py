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
from flow_agent.proactive.judge_loop import JudgeLoop
from flow_agent.proactive.models import DataItem
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
    # New architecture: JudgeLoop async LLM tool-call loop for content classification
    from flow_agent.proactive.models import GatewayResult
    class _FakeLLM:
        def generate(self, messages, tools=None):
            class _R:
                content = ""
                tool_calls = []
            return _R()
    judge = JudgeLoop(llm_client=_FakeLLM(), max_steps=1)
    gateway = GatewayResult(alerts=[
        DataItem(source="alert", item_id="a", title="test", summary="test", priority_hint=0.9)
    ])
    import asyncio
    result = asyncio.run(judge.evaluate(gateway))
    assert result.decision in {"reply", "skip"}


def test_subagent_parent_child_trace_and_poll(tmp_path: Path):
    mgr = SubagentManager(tasks_path=tmp_path / "tasks.jsonl")
    task = mgr.create_task("code", {"x": 1}, parent_trace_id="trace-parent-1")
    mgr.run_task(task, executor=lambda t: {"ok": True, "kind": t.kind})
    time.sleep(0.05)
    rows = mgr.list_recent_tasks(limit=5)
    assert any(row.get("parent_trace_id") == "trace-parent-1" for row in rows)


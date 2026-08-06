import time
from pathlib import Path

from application.memory.app.profile_extractor import ProfileExtractor
from application.proactive.app.judge_loop import JudgeLoop
from application.proactive.domain.models import DataItem
from application.delegation.app.manager import SubagentManager


def test_profile_extractor():
    profile = ProfileExtractor().extract([
        {"role": "user", "content": "我叫小明"},
        {"role": "user", "content": "我喜欢跑步"},
    ])
    assert len(profile.identity) >= 1
    assert len(profile.preference) >= 1


def test_proactive_judge_decision():
    # New architecture: JudgeLoop async LLM tool-call loop for content classification
    from application.proactive.domain.models import GatewayResult
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

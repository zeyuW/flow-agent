"""漂移模式单元测试：技能扫描、工具分发、管道执行、状态持久化。"""

import json
import asyncio
from pathlib import Path

import pytest

from flow_agent.proactive.drift_models import DriftSkill, DriftRun, DriftTick
from flow_agent.proactive.drift_pipeline import DriftTurnPipeline
from flow_agent.proactive.drift_store import DriftStateStore
from flow_agent.proactive.drift_tools import (
    dispatch_drift_tool,
    get_drift_tool_schemas,
    get_post_push_tool_schemas,
)
from flow_agent.proactive.gate import ProactiveStateStore
from flow_agent.llm.client import LLMToolCall


# ── 工具函数测试 ──

def test_drift_tool_schemas_have_all_tools():
    schemas = get_drift_tool_schemas()
    names = {t["function"]["name"] for t in schemas}
    assert names == {"read_file", "write_file", "message_push", "finish_drift"}


def test_post_push_schemas_are_restricted():
    schemas = get_post_push_tool_schemas()
    names = {t["function"]["name"] for t in schemas}
    assert names == {"write_file", "finish_drift"}


def test_dispatch_read_file(tmp_path):
    path = tmp_path / "test.txt"
    path.write_text("hello world", encoding="utf-8")
    result = dispatch_drift_tool(
        "read_file",
        {"path": str(path)},
        {"workspace": str(tmp_path)},
    )
    assert "hello world" in result


def test_dispatch_write_file(tmp_path):
    path = tmp_path / "out.txt"
    result = dispatch_drift_tool(
        "write_file",
        {"path": str(path), "content": "data"},
        {"workspace": str(tmp_path)},
    )
    assert "写入成功" in result
    assert path.read_text(encoding="utf-8") == "data"


def test_dispatch_rejects_path_outside_drift_workspace(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    result = dispatch_drift_tool(
        "write_file",
        {"path": str(outside), "content": "data"},
        {"workspace": str(tmp_path)},
    )
    assert "越出漂移工作目录" in result
    assert not outside.exists()


def test_dispatch_message_push():
    ctx = {"message": "", "pushed": False}
    result = dispatch_drift_tool("message_push", {"text": "hello user"}, ctx)
    assert ctx["message"] == "hello user"
    assert ctx["pushed"] is True


def test_dispatch_finish_drift(tmp_path):
    skill_dir = tmp_path / "test_skill"
    skill_dir.mkdir()
    skill = DriftSkill(name="test", path=str(skill_dir))
    ctx = {"skills": [skill], "runs": [], "finished": False, "workspace": str(tmp_path)}

    result = dispatch_drift_tool(
        "finish_drift",
        {"summary": "完成测试", "skill_name": "test", "next_step": "继续"},
        ctx,
    )
    assert ctx["finished"] is True
    assert len(ctx["runs"]) == 1
    assert ctx["runs"][0].skill_name == "test"
    assert skill.state["run_count"] == 1
    assert skill.state["next"] == "继续"


# ── 状态存储测试 ──

def test_store_scan_empty_skills(tmp_path):
    store = DriftStateStore(tmp_path)
    skills = store.scan_skills()
    assert skills == []


def test_store_scan_and_filter_skills(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    s1 = skills_dir / "skill_a"
    s1.mkdir()
    (s1 / "skill.json").write_text(
        json.dumps({"name": "a", "description": "skill a", "requires_mcp": ["mcp_x"]}),
        encoding="utf-8",
    )
    s2 = skills_dir / "skill_b"
    s2.mkdir()
    (s2 / "skill.json").write_text(
        json.dumps({"name": "b", "description": "skill b"}),
        encoding="utf-8",
    )

    store = DriftStateStore(tmp_path)
    all_skills = store.scan_skills()
    assert len(all_skills) == 2

    filtered = store.filter_by_mcp(all_skills, {"mcp_x"})
    assert len(filtered) == 2  # 两个技能均满足依赖，b 不要求 MCP

    filtered2 = store.filter_by_mcp(all_skills, {"mcp_y"})
    assert len(filtered2) == 1  # 只有不要求 MCP 的 b 可执行
    assert filtered2[0].name == "b"


def test_store_history_append_and_load(tmp_path):
    store = DriftStateStore(tmp_path)
    tick = DriftTick(
        runs=[
            DriftRun(skill_name="s1", action="did something", result="ok"),
            DriftRun(skill_name="s2", action="did more", result="ok"),
        ]
    )
    store.append_run(tick)
    history = store.load_history()
    assert len(history) == 2
    assert history[0].skill_name == "s1"
    assert history[1].skill_name == "s2"


def test_store_history_returns_recent_window_without_deleting_older_runs(tmp_path):
    store = DriftStateStore(tmp_path)
    for i in range(15):
        tick = DriftTick(runs=[DriftRun(skill_name=f"s{i}", action="test")])
        store.append_run(tick)
    history = store.load_history()
    assert len(history) == 10
    assert history[-1].skill_name == "s14"
    assert len(store.load_history(limit=20)) == 15
    store.close()


def test_store_save_skill_state(tmp_path):
    skill_dir = tmp_path / "skills" / "test"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.json").write_text(
        json.dumps({"name": "test"}),
        encoding="utf-8",
    )
    skill = DriftSkill(name="test", path=str(skill_dir), state={"run_count": 3})
    store = DriftStateStore(tmp_path)
    store.save_skill_state(skill)
    state_file = skill_dir / "state.json"
    assert state_file.is_file()
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["run_count"] == 3

    store.close()
    restored = DriftStateStore(tmp_path)
    restored_skill = restored.scan_skills()[0]
    assert restored_skill.state["run_count"] == 3
    restored.close()


def test_store_loads_skill_instructions(tmp_path):
    skill_dir = tmp_path / "skills" / "research"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.json").write_text(
        json.dumps({"name": "research", "description": "整理研究笔记"}),
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text("先读取资料，再生成摘要。", encoding="utf-8")

    store = DriftStateStore(tmp_path)
    skill = store.scan_skills()[0]
    assert "生成摘要" in skill.instructions
    store.close()


def test_store_rejects_corrupted_skill_state(tmp_path):
    skill_dir = tmp_path / "skills" / "broken"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.json").write_text(
        json.dumps({"name": "broken"}),
        encoding="utf-8",
    )
    (skill_dir / "state.json").write_text("{broken", encoding="utf-8")
    store = DriftStateStore(tmp_path)

    with pytest.raises(ValueError, match="漂移技能状态损坏"):
        store.scan_skills()
    store.close()


def test_drift_pipeline_executes_skill_and_persists_continuum(tmp_path):
    skill_dir = tmp_path / "skills" / "research"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.json").write_text(
        json.dumps({"name": "research", "description": "整理研究笔记"}),
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text("读取 notes.txt 后记录进度。", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("资料", encoding="utf-8")

    class LLM:
        def __init__(self):
            self.calls = 0

        def generate(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return type("Response", (), {
                    "content": "",
                    "tool_calls": [LLMToolCall(
                        id="read-1",
                        name="read_file",
                        arguments={"path": "notes.txt"},
                        arguments_json='{"path":"notes.txt"}',
                    )],
                })()
            assert messages[-1]["tool_call_id"] == "read-1"
            assert "资料" in messages[-1]["content"]
            return type("Response", (), {
                "content": "",
                "tool_calls": [LLMToolCall(
                    id="finish-1",
                    name="finish_drift",
                    arguments={
                        "skill_name": "research",
                        "summary": "已整理资料",
                        "next_step": "生成摘要",
                    },
                    arguments_json="{}",
                )],
            })()

    store = DriftStateStore(tmp_path)
    pipeline = DriftTurnPipeline(
        state_store=store,
        llm_client=LLM(),
        workspace=str(tmp_path),
    )

    tick = asyncio.run(pipeline.run(connected_mcp=set()))

    assert tick.finished is True
    assert tick.runs[0].status == "completed"
    restored_skill = store.scan_skills()[0]
    assert restored_skill.state["run_count"] == 1
    assert restored_skill.state["next"] == "生成摘要"
    assert store.load_history()[0].action == "已整理资料"
    pipeline.close()


# ── ProactiveStateStore drift 时间戳测试 ──

def test_state_store_drift_timestamp():
    store = ProactiveStateStore()
    assert store.get_drift_last_at() == 0.0
    store.mark_drift_run()
    assert store.get_drift_last_at() > 0.0

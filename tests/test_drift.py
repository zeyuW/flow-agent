"""漂移模式单元测试：技能扫描、工具分发、管道执行、状态持久化。"""

import json
from pathlib import Path

import pytest

from flow_agent.proactive.drift_models import DriftSkill, DriftRun, DriftTick
from flow_agent.proactive.drift_store import DriftStateStore
from flow_agent.proactive.drift_tools import (
    dispatch_drift_tool,
    get_drift_tool_schemas,
    get_post_push_tool_schemas,
)
from flow_agent.proactive.gate import ProactiveStateStore


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
    result = dispatch_drift_tool("read_file", {"path": str(path)}, {})
    assert "hello world" in result


def test_dispatch_write_file(tmp_path):
    path = tmp_path / "out.txt"
    result = dispatch_drift_tool("write_file", {"path": str(path), "content": "data"}, {})
    assert "写入成功" in result
    assert path.read_text(encoding="utf-8") == "data"


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
    assert len(filtered) == 2  # both pass, "b" has no MCP requirement

    filtered2 = store.filter_by_mcp(all_skills, {"mcp_y"})
    assert len(filtered2) == 1  # only "b" passes
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


def test_store_history_capped_at_10(tmp_path):
    store = DriftStateStore(tmp_path)
    for i in range(15):
        tick = DriftTick(runs=[DriftRun(skill_name=f"s{i}", action="test")])
        store.append_run(tick)
    history = store.load_history()
    assert len(history) == 10
    assert history[-1].skill_name == "s14"


def test_store_save_skill_state(tmp_path):
    skill_dir = tmp_path / "skills" / "test"
    skill_dir.mkdir(parents=True)
    skill = DriftSkill(name="test", path=str(skill_dir), state={"run_count": 3})
    store = DriftStateStore(tmp_path)
    store.save_skill_state(skill)
    state_file = skill_dir / "state.json"
    assert state_file.is_file()
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["run_count"] == 3


# ── ProactiveStateStore drift 时间戳测试 ──

def test_state_store_drift_timestamp():
    store = ProactiveStateStore()
    assert store.get_drift_last_at() == 0.0
    store.mark_drift_run()
    assert store.get_drift_last_at() > 0.0

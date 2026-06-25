"""漂移状态存储：技能扫描与运行历史持久化 (spec 2a-2d, 5a-5d)。"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone

from flow_agent.proactive.drift_models import DriftSkill, DriftRun, DriftTick

logger = logging.getLogger(__name__)

_MAX_RECENT_RUNS = 10


class DriftStateStore:
    """管理漂移技能的扫描、过滤和状态持久化。"""

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)

    # ── 技能扫描 (spec 2a-2d) ──

    def scan_skills(self) -> list[DriftSkill]:
        """扫描 drift/skills/ 目录下的所有技能。"""
        skills_dir = self._data_dir / "skills"
        if not skills_dir.is_dir():
            return []
        skills = []
        for d in sorted(skills_dir.iterdir()):
            if not d.is_dir():
                continue
            skill = self._load_skill(d)
            if skill:
                skills.append(skill)
        return skills

    def filter_by_mcp(self, skills: list[DriftSkill], connected_mcp: set[str]) -> list[DriftSkill]:
        """过滤掉 requires_mcp 中有未连接 MCP server 的技能 (spec 2c)。"""
        return [s for s in skills if not s.requires_mcp or set(s.requires_mcp).issubset(connected_mcp)]

    def _load_skill(self, skill_dir: Path) -> DriftSkill | None:
        manifest = skill_dir / "skill.json"
        if not manifest.is_file():
            return None
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        state = {}
        state_file = skill_dir / "state.json"
        if state_file.is_file():
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return DriftSkill(
            name=data.get("name", skill_dir.name),
            description=data.get("description", ""),
            requires_mcp=data.get("requires_mcp", []),
            state=state,
            path=str(skill_dir),
        )

    # ── 运行历史 (spec 5b-5c) ──

    def load_history(self) -> list[DriftRun]:
        """加载漂移运行历史。"""
        hist_file = self._data_dir / "drift.json"
        if not hist_file.is_file():
            return []
        try:
            data = json.loads(hist_file.read_text(encoding="utf-8"))
            runs = data.get("recent_runs", [])
            return [DriftRun(**r) for r in runs]
        except (json.JSONDecodeError, OSError):
            return []

    def append_run(self, tick: DriftTick) -> None:
        """追加本次运行记录到历史，保留最近 10 条 (spec 5c)。"""
        now = datetime.now(timezone.utc).isoformat()
        history = self.load_history()
        for run in tick.runs:
            run.timestamp = now
            history.append(run)
        if len(history) > _MAX_RECENT_RUNS:
            history = history[-_MAX_RECENT_RUNS:]
        self._save_history(history)

    def _save_history(self, runs: list[DriftRun]) -> None:
        hist_file = self._data_dir / "drift.json"
        data = {
            "recent_runs": [
                {
                    "skill_name": r.skill_name,
                    "action": r.action,
                    "result": r.result,
                    "timestamp": r.timestamp,
                }
                for r in runs
            ],
        }
        hist_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 技能状态 (spec 5a) ──

    def save_skill_state(self, skill: DriftSkill) -> None:
        """保存单个技能的状态到 state.json (spec 5a)。"""
        state_file = Path(skill.path) / "state.json"
        state_file.write_text(json.dumps(skill.state, ensure_ascii=False, indent=2), encoding="utf-8")

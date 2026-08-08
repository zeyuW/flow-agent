"""漂移技能状态和运行历史的持久化存储。"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from application.proactive.domain.drift import DriftRun, DriftSkill, DriftTick

logger = logging.getLogger(__name__)

_MAX_RECENT_RUNS = 200


class DriftStateStore:
    """以 SQLite 保存连续状态，并兼容技能目录中的 state.json。"""

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(
            str(self._data_dir / "drift.db"),
            check_same_thread=False,
        )
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS drift_runs ("
            "run_id TEXT PRIMARY KEY, skill_name TEXT NOT NULL, action TEXT NOT NULL, "
            "result TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL, "
            "finished_at TEXT, error TEXT NOT NULL)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS drift_skill_state ("
            "skill_name TEXT PRIMARY KEY, state_json TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        self._db.commit()
        self._import_legacy_history()

    def scan_skills(self) -> list[DriftSkill]:
        """扫描技能清单、说明正文和上次连续状态。"""

        skills_dir = self._data_dir / "skills"
        if not skills_dir.is_dir():
            return []
        skills: list[DriftSkill] = []
        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill = self._load_skill(skill_dir)
            if skill is not None:
                skills.append(skill)
        return skills

    def filter_by_mcp(
        self,
        skills: list[DriftSkill],
        connected_mcp: set[str],
    ) -> list[DriftSkill]:
        """只保留依赖均已连接的漂移技能。"""

        return [
            skill
            for skill in skills
            if not skill.requires_mcp
            or set(skill.requires_mcp).issubset(connected_mcp)
        ]

    def _load_skill(self, skill_dir: Path) -> DriftSkill | None:
        manifest = skill_dir / "skill.json"
        if not manifest.is_file():
            return None
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"漂移技能清单损坏: {manifest}") from exc
        name = str(data.get("name") or skill_dir.name)
        state = self._load_skill_state(name, skill_dir)
        instructions_file = skill_dir / "SKILL.md"
        instructions = (
            instructions_file.read_text(encoding="utf-8")
            if instructions_file.is_file()
            else ""
        )
        return DriftSkill(
            name=name,
            description=str(data.get("description") or ""),
            requires_mcp=[str(item) for item in data.get("requires_mcp", [])],
            state=state,
            path=str(skill_dir),
            instructions=instructions,
        )

    def _load_skill_state(self, name: str, skill_dir: Path) -> dict:
        with self._lock:
            row = self._db.execute(
                "SELECT state_json FROM drift_skill_state WHERE skill_name = ?",
                (name,),
            ).fetchone()
        if row is not None:
            try:
                value = json.loads(str(row[0]))
            except json.JSONDecodeError as exc:
                raise ValueError(f"漂移技能数据库状态损坏: {name}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"漂移技能数据库状态根节点必须是对象: {name}")
            return value
        state_file = skill_dir / "state.json"
        if not state_file.is_file():
            return {}
        try:
            value = json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError(f"漂移技能状态损坏: {state_file}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"漂移技能状态根节点必须是对象: {state_file}")
        return value

    def load_history(self, limit: int = 10) -> list[DriftRun]:
        """按时间正序返回最近的漂移运行历史。"""

        with self._lock:
            rows = self._db.execute(
                "SELECT run_id, skill_name, action, result, status, started_at, "
                "finished_at, error FROM drift_runs "
                "ORDER BY started_at DESC, rowid DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [
            DriftRun(
                run_id=str(row[0]),
                skill_name=str(row[1]),
                action=str(row[2]),
                result=str(row[3]),
                status=str(row[4]),
                timestamp=str(row[5]),
                finished_at=str(row[6] or ""),
                error=str(row[7] or ""),
            )
            for row in reversed(rows)
        ]

    def append_run(self, tick: DriftTick) -> None:
        """追加本轮全部运行记录，不裁掉连续性状态。"""

        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            for run in tick.runs:
                if not run.timestamp:
                    run.timestamp = now
                if not run.finished_at and run.status != "running":
                    run.finished_at = now
                self._db.execute(
                    "INSERT INTO drift_runs "
                    "(run_id, skill_name, action, result, status, started_at, finished_at, error) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(run_id) DO UPDATE SET action=excluded.action, "
                    "result=excluded.result, status=excluded.status, "
                    "finished_at=excluded.finished_at, error=excluded.error",
                    (
                        run.run_id,
                        run.skill_name,
                        run.action,
                        run.result,
                        run.status,
                        run.timestamp,
                        run.finished_at or None,
                        run.error,
                    ),
                )
            self._db.commit()

    def save_skill_state(self, skill: DriftSkill) -> None:
        """原子保存技能连续状态，并同步兼容 state.json。"""

        payload = json.dumps(skill.state, ensure_ascii=False, indent=2)
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._db.execute(
                "INSERT INTO drift_skill_state(skill_name, state_json, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(skill_name) DO UPDATE SET "
                "state_json=excluded.state_json, updated_at=excluded.updated_at",
                (skill.name, payload, now),
            )
            self._db.commit()
        state_file = Path(skill.path) / "state.json"
        temporary = state_file.with_suffix(".json.tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(state_file)

    def close(self) -> None:
        """关闭漂移状态数据库。"""

        with self._lock:
            self._db.close()

    def _import_legacy_history(self) -> None:
        """首次启动时导入旧 drift.json，原文件继续保留。"""

        with self._lock:
            count = self._db.execute("SELECT COUNT(*) FROM drift_runs").fetchone()[0]
        legacy = self._data_dir / "drift.json"
        if count or not legacy.is_file():
            return
        try:
            raw = json.loads(legacy.read_text(encoding="utf-8"))
            runs = raw.get("recent_runs", [])
            tick = DriftTick(runs=[DriftRun(**item) for item in runs])
            self.append_run(tick)
        except (json.JSONDecodeError, OSError, TypeError):
            logger.exception("旧漂移历史导入失败: %s", legacy)

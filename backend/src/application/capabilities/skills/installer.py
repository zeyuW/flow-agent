"""从 Git 仓库安装用户 Skill。"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class InstalledSkill:
    name: str


@dataclass(frozen=True, slots=True)
class SkillCandidate:
    name: str
    directory: Path


class SkillInstaller:
    """管理 ~/.flow/skills 下的 Git Skill。"""

    def __init__(self, installed_dir: Path) -> None:
        self._installed_dir = installed_dir

    def scan(self, repository_url: str) -> list[SkillCandidate]:
        self._installed_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self._installed_dir) as temporary_dir:
            clone_dir = self._clone(repository_url, Path(temporary_dir))
            return self._find_candidates(clone_dir)

    def install(
        self, repository_url: str, names: list[str] | None = None
    ) -> InstalledSkill | list[InstalledSkill]:
        self._installed_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self._installed_dir) as temporary_dir:
            clone_dir = self._clone(repository_url, Path(temporary_dir))
            candidates = self._find_candidates(clone_dir)
            selected_names = names or [candidate.name for candidate in candidates]
            selected = self._select_candidates(candidates, selected_names)
            for candidate in selected:
                destination = self._installed_dir / candidate.name
                if destination.exists():
                    raise ValueError(f"Skill 已安装: {candidate.name}")
            for candidate in selected:
                shutil.move(
                    str(candidate.directory), self._installed_dir / candidate.name
                )
        installed = [InstalledSkill(name=candidate.name) for candidate in selected]
        return installed if names is not None else installed[0]

    def uninstall(self, name: str) -> None:
        if not name or Path(name).name != name:
            raise ValueError("无效的 Skill 名称")
        skill_dir = self._installed_dir / name
        if not skill_dir.is_dir():
            raise ValueError(f"未找到已安装 Skill: {name}")
        shutil.rmtree(skill_dir)

    def _clone(self, repository_url: str, temporary_dir: Path) -> Path:
        clone_dir = temporary_dir / self._repository_name(repository_url)
        result = subprocess.run(
            ["git", "clone", "--depth", "1", repository_url, str(clone_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise ValueError(f"无法拉取 Skill 仓库: {result.stderr.strip()}")
        return clone_dir

    @staticmethod
    def _find_candidates(clone_dir: Path) -> list[SkillCandidate]:
        skill_files = []
        root_skill = clone_dir / "SKILL.md"
        if root_skill.is_file():
            skill_files.append(root_skill)
        skill_files.extend(sorted((clone_dir / "skills").glob("*/SKILL.md")))
        candidates = [
            SkillCandidate(name=skill_file.parent.name, directory=skill_file.parent)
            for skill_file in skill_files
        ]
        if not candidates:
            raise ValueError("仓库中未找到 SKILL.md 或 skills/*/SKILL.md")
        return candidates

    @staticmethod
    def _select_candidates(
        candidates: list[SkillCandidate], names: list[str]
    ) -> list[SkillCandidate]:
        by_name = {candidate.name: candidate for candidate in candidates}
        missing = [name for name in names if name not in by_name]
        if missing:
            raise ValueError(f"仓库中未找到 Skill: {', '.join(missing)}")
        return [by_name[name] for name in names]

    @staticmethod
    def _repository_name(repository_url: str) -> str:
        path = urlparse(repository_url).path.rstrip("/")
        name = Path(path).name.removesuffix(".git")
        if not name or name in {".", ".."}:
            raise ValueError("无法从仓库地址识别 Skill 名称")
        return name

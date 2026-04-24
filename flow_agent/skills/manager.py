from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from flow_agent.skills.manifest import SkillManifest


@dataclass(slots=True)
class SkillManager:
    skills_dir: Path

    def scan(self) -> list[SkillManifest]:
        if not self.skills_dir.exists():
            return []
        rows: list[SkillManifest] = []
        for manifest_file in sorted(self.skills_dir.glob("*/skill.json")):
            rows.append(SkillManifest.from_file(manifest_file))
        return rows

    def install(self, source: Path) -> SkillManifest:
        if not source.exists() or not source.is_dir():
            raise ValueError(f"invalid skill path: {source}")
        source_manifest = source / "skill.json"
        if not source_manifest.exists():
            raise ValueError("skill.json not found in skill path")
        manifest = SkillManifest.from_file(source_manifest)
        target = self.skills_dir / manifest.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
        return manifest

    def uninstall(self, name: str) -> None:
        target = self.skills_dir / name
        if target.exists():
            shutil.rmtree(target)

    def enable(self, name: str) -> None:
        self._set_enabled(name, True)

    def disable(self, name: str) -> None:
        self._set_enabled(name, False)

    def _set_enabled(self, name: str, enabled: bool) -> None:
        manifest_file = self.skills_dir / name / "skill.json"
        if not manifest_file.exists():
            raise ValueError(f"skill not found: {name}")
        manifest = SkillManifest.from_file(manifest_file)
        manifest.enabled = enabled
        manifest.write_to(manifest_file)

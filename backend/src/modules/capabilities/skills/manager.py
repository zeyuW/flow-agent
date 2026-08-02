from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from modules.capabilities.skills.manifest import SkillManifest


@dataclass(slots=True)
class InstallReport:
    name: str
    installed: bool
    rollback_performed: bool
    reason: str = "ok"
    metadata: dict[str, str] | None = None


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
        report = self.install_with_report(source)
        if not report.installed:
            raise ValueError(report.reason)
        source_manifest = source / "skill.json"
        return SkillManifest.from_file(source_manifest)

    def install_with_report(self, source: Path) -> InstallReport:
        if not source.exists() or not source.is_dir():
            return InstallReport(name=source.name, installed=False, rollback_performed=False, reason=f"invalid skill path: {source}")
        source_manifest = source / "skill.json"
        if not source_manifest.exists():
            return InstallReport(name=source.name, installed=False, rollback_performed=False, reason="skill.json not found in skill path")
        manifest = SkillManifest.from_file(source_manifest)
        target = self.skills_dir / manifest.name
        backup = self.skills_dir / f".{manifest.name}.bak"
        rollback = False
        if target.exists():
            if backup.exists():
                shutil.rmtree(backup)
            shutil.move(target, backup)
        try:
            shutil.copytree(source, target)
            if backup.exists():
                shutil.rmtree(backup)
            return InstallReport(
                name=manifest.name,
                installed=True,
                rollback_performed=False,
                metadata={"version": manifest.version, "compatibility": manifest.compatibility},
            )
        except Exception as exc:
            rollback = True
            if target.exists():
                shutil.rmtree(target)
            if backup.exists():
                shutil.move(backup, target)
            return InstallReport(
                name=manifest.name,
                installed=False,
                rollback_performed=rollback,
                reason=str(exc),
            )

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

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from application.capabilities.plugins.models import PluginManifest


@dataclass(slots=True)
class InstallReport:
    name: str
    installed: bool
    rollback_performed: bool
    reason: str = "ok"
    metadata: dict[str, str] | None = None


@dataclass(slots=True)
class PluginManager:
    plugins_dir: Path

    def scan(self) -> list[PluginManifest]:
        if not self.plugins_dir.exists():
            return []
        rows: list[PluginManifest] = []
        for manifest_file in sorted(self.plugins_dir.glob("*/plugin.json")):
            rows.append(PluginManifest.from_file(manifest_file))
        return rows

    def install(self, source: Path) -> PluginManifest:
        report = self.install_with_report(source)
        if not report.installed:
            raise ValueError(report.reason)
        source_manifest = source / "plugin.json"
        return PluginManifest.from_file(source_manifest)

    def install_with_report(self, source: Path) -> InstallReport:
        if not source.exists() or not source.is_dir():
            return InstallReport(name=source.name, installed=False, rollback_performed=False, reason=f"invalid plugin path: {source}")
        source_manifest = source / "plugin.json"
        if not source_manifest.exists():
            return InstallReport(name=source.name, installed=False, rollback_performed=False, reason="plugin.json not found in plugin path")
        manifest = PluginManifest.from_file(source_manifest)
        target = self.plugins_dir / manifest.name
        backup = self.plugins_dir / f".{manifest.name}.bak"
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
            if target.exists():
                shutil.rmtree(target)
            if backup.exists():
                shutil.move(backup, target)
            return InstallReport(
                name=manifest.name,
                installed=False,
                rollback_performed=True,
                reason=str(exc),
            )

    def uninstall(self, name: str) -> None:
        target = self.plugins_dir / name
        if target.exists():
            shutil.rmtree(target)

    def enable(self, name: str) -> None:
        self._set_enabled(name, True)

    def disable(self, name: str) -> None:
        self._set_enabled(name, False)

    def _set_enabled(self, name: str, enabled: bool) -> None:
        manifest_file = self.plugins_dir / name / "plugin.json"
        if not manifest_file.exists():
            raise ValueError(f"plugin not found: {name}")
        manifest = PluginManifest.from_file(manifest_file)
        manifest.enabled = enabled
        manifest.write_to(manifest_file)

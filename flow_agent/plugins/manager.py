from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from flow_agent.plugins.models import PluginManifest


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
        if not source.exists() or not source.is_dir():
            raise ValueError(f"invalid plugin path: {source}")
        source_manifest = source / "plugin.json"
        if not source_manifest.exists():
            raise ValueError("plugin.json not found in plugin path")
        manifest = PluginManifest.from_file(source_manifest)
        target = self.plugins_dir / manifest.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
        return manifest

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

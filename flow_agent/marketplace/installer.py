from __future__ import annotations

from dataclasses import dataclass

from flow_agent.marketplace.index import MarketplaceIndex
from flow_agent.marketplace.models import ExtensionRecord
from flow_agent.plugins.manager import PluginManager
from flow_agent.skills.manager import SkillManager


@dataclass(slots=True)
class MarketplaceInstaller:
    index: MarketplaceIndex
    skills: SkillManager
    plugins: PluginManager

    def rebuild_local_index(self) -> list[ExtensionRecord]:
        rows: list[ExtensionRecord] = []
        for skill in self.skills.scan():
            rows.append(
                ExtensionRecord(
                    kind="skill",
                    name=skill.name,
                    version=skill.version,
                    enabled=skill.enabled,
                    compatibility=skill.compatibility,
                    metadata=skill.metadata,
                )
            )
        for plugin in self.plugins.scan():
            rows.append(
                ExtensionRecord(
                    kind="plugin",
                    name=plugin.name,
                    version=plugin.version,
                    enabled=plugin.enabled,
                    compatibility=plugin.compatibility,
                    metadata=plugin.metadata,
                )
            )
        self.index.save(rows)
        return rows

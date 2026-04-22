import logging
from pathlib import Path

from flow_agent.skills.models import SkillSpec


logger = logging.getLogger(__name__)


class SkillLoader:
    """Scan skills directory and parse basic metadata from SKILL.md."""

    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir

    def load(self) -> list[SkillSpec]:
        if not self.skills_dir.exists():
            return []
        specs: list[SkillSpec] = []
        for skill_md in self.skills_dir.glob("*/SKILL.md"):
            try:
                specs.append(self._parse_skill_file(skill_md))
            except Exception:
                logger.exception("failed parsing skill file: %s", skill_md)
        return specs

    def _parse_skill_file(self, skill_file: Path) -> SkillSpec:
        lines = skill_file.read_text(encoding="utf-8").splitlines()
        name = skill_file.parent.name
        description = "no description"
        requires_tools: list[str] = []
        requires_sources: list[str] = []
        requires_mcp: list[str] = []
        for line in lines:
            clean = line.strip()
            if clean.lower().startswith("name:"):
                name = clean.split(":", 1)[1].strip() or name
            elif clean.lower().startswith("description:"):
                description = clean.split(":", 1)[1].strip() or description
            elif clean.lower().startswith("requires_tools:"):
                requires_tools = _parse_csv(clean)
            elif clean.lower().startswith("requires_sources:"):
                requires_sources = _parse_csv(clean)
            elif clean.lower().startswith("requires_mcp:"):
                requires_mcp = _parse_csv(clean)
        return SkillSpec(
            name=name,
            description=description,
            path=str(skill_file),
            requires_tools=requires_tools,
            requires_sources=requires_sources,
            requires_mcp=requires_mcp,
        )


def _parse_csv(line: str) -> list[str]:
    payload = line.split(":", 1)[1].strip()
    if not payload:
        return []
    return [item.strip() for item in payload.split(",") if item.strip()]


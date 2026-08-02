import logging
from pathlib import Path

from modules.capabilities.skills.models import SkillSpec


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
        requires_vision_model = False
        requires_image_output = False
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
            elif clean.lower().startswith("requires_vision_model:"):
                requires_vision_model = _parse_bool(clean)
            elif clean.lower().startswith("requires_image_output:"):
                requires_image_output = _parse_bool(clean)
        return SkillSpec(
            name=name,
            description=description,
            path=str(skill_file),
            requires_tools=requires_tools,
            requires_sources=requires_sources,
            requires_mcp=requires_mcp,
            requires_vision_model=requires_vision_model,
            requires_image_output=requires_image_output,
        )


def _parse_csv(line: str) -> list[str]:
    payload = line.split(":", 1)[1].strip()
    if not payload:
        return []
    return [item.strip() for item in payload.split(",") if item.strip()]


def _parse_bool(line: str) -> bool:
    """仅接受明确真值，避免 Skill 声明被任意字符串意外开启。"""

    return line.split(":", 1)[1].strip().lower() in {"1", "true", "yes"}

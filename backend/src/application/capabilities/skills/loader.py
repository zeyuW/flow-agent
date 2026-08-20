import logging
from pathlib import Path
from typing import Any

import yaml

from application.capabilities.skills.models import SkillSpec

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
        text = skill_file.read_text(encoding="utf-8")
        metadata = _read_metadata(text)
        name = skill_file.parent.name
        description = "no description"
        requires_tools: list[str] = []
        requires_sources: list[str] = []
        requires_mcp: list[str] = []
        requires_vision_model = False
        requires_image_output = False
        name = _text_value(metadata, "name") or name
        description = _text_value(metadata, "description") or description
        requires_tools = _list_value(metadata, "requires_tools")
        requires_sources = _list_value(metadata, "requires_sources")
        requires_mcp = _list_value(metadata, "requires_mcp")
        requires_vision_model = _bool_value(metadata, "requires_vision_model")
        requires_image_output = _bool_value(metadata, "requires_image_output")
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


def _read_metadata(text: str) -> dict[str, Any]:
    if text.startswith("---\n"):
        _, frontmatter, _ = text.split("---", 2)
        parsed = yaml.safe_load(frontmatter)
        if parsed is None:
            return {}
        if not isinstance(parsed, dict):
            raise ValueError("SKILL.md frontmatter 必须是对象")
        return parsed

    metadata: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip().lower()] = value.strip()
    return metadata


def _text_value(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    return value.strip() if isinstance(value, str) else ""


def _list_value(metadata: dict[str, Any], key: str) -> list[str]:
    value = metadata.get(key)
    if isinstance(value, list):
        return [
            item.strip() for item in value if isinstance(item, str) and item.strip()
        ]
    if isinstance(value, str):
        return [item.strip() for item in value.strip("[]").split(",") if item.strip()]
    return []


def _bool_value(metadata: dict[str, Any], key: str) -> bool:
    """仅接受明确真值，避免 Skill 声明被任意字符串意外开启。"""

    value = metadata.get(key)
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.lower() in {"1", "true", "yes"}

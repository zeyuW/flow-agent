from dataclasses import dataclass, field


@dataclass(slots=True)
class SkillSpec:
    """Skill definition loaded from a SKILL.md file."""

    name: str
    description: str
    path: str
    requires_tools: list[str] = field(default_factory=list)
    requires_sources: list[str] = field(default_factory=list)
    requires_mcp: list[str] = field(default_factory=list)
    requires_vision_model: bool = False
    requires_image_output: bool = False

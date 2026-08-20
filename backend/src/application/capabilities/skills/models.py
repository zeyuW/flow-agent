from dataclasses import dataclass, field
from typing import Literal

SkillSource = Literal["builtin", "project", "installed"]
SkillStatus = Literal["available", "conflict"]


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


@dataclass(slots=True)
class SkillCatalogItem:
    """带来源与可用状态的普通 Skill。"""

    spec: SkillSpec
    source: SkillSource
    status: SkillStatus = "available"
    reason: str | None = None

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def description(self) -> str:
        return self.spec.description

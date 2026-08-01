from flow_agent.skills.models import SkillSpec


class SkillRegistry:
    """In-memory registry for loaded skills."""

    def __init__(self, skills: list[SkillSpec] | None = None) -> None:
        self._skills = {skill.name: skill for skill in (skills or [])}

    def register(self, skill: SkillSpec) -> None:
        self._skills[skill.name] = skill

    def list_skills(self) -> list[SkillSpec]:
        return list(self._skills.values())

    def select(
        self,
        *,
        available_tools: set[str],
        available_sources: set[str],
        available_mcp: set[str],
    ) -> SkillSpec | None:
        for skill in self.list_skills():
            if any(name not in available_tools for name in skill.requires_tools):
                continue
            if any(name not in available_sources for name in skill.requires_sources):
                continue
            if any(name not in available_mcp for name in skill.requires_mcp):
                continue
            return skill
        return None


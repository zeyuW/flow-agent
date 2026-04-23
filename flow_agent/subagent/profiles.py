from dataclasses import dataclass


@dataclass(slots=True)
class SubagentProfile:
    name: str
    task_types: tuple[str, ...]


class SubagentRouter:
    """Route task type to best profile."""

    def __init__(self, profiles: list[SubagentProfile]) -> None:
        self.profiles = profiles

    def route(self, task_kind: str) -> SubagentProfile | None:
        for profile in self.profiles:
            if task_kind in profile.task_types:
                return profile
        return self.profiles[0] if self.profiles else None


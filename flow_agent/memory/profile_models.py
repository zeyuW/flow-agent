from dataclasses import dataclass, field


@dataclass(slots=True)
class UserProfile:
    identity: list[str] = field(default_factory=list)
    preference: list[str] = field(default_factory=list)
    goal: list[str] = field(default_factory=list)
    constraint: list[str] = field(default_factory=list)
    milestone: list[str] = field(default_factory=list)
    routine: list[str] = field(default_factory=list)


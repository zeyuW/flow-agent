from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class CommandPermissions:
    role_rules: dict[str, set[str]] = field(
        default_factory=lambda: {
            "admin": {
                "runtime.start",
                "runtime.stop",
                "runtime.restart",
                "runtime.reload",
                "skills.install",
                "skills.enable",
                "skills.disable",
                "plugins.install",
                "plugins.uninstall",
                "plugins.enable",
                "plugins.disable",
            },
            "user": set(),
        }
    )

    def allowed(self, role: str, action: str) -> bool:
        if role == "admin":
            return True
        return action in self.role_rules.get(role, set())

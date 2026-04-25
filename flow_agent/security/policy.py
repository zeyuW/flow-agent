from __future__ import annotations

from dataclasses import dataclass, field

from flow_agent.security.permissions import CommandPermissions


@dataclass(slots=True)
class SecurityPolicy:
    command_permissions: CommandPermissions = field(default_factory=CommandPermissions)
    channel_allowlist: set[str] = field(default_factory=set)
    channel_denylist: set[str] = field(default_factory=set)

    def check_command(self, role: str, action: str) -> tuple[bool, str]:
        if self.command_permissions.allowed(role, action):
            return True, "ok"
        return False, f"forbidden action={action} role={role}"

    def check_channel_source(self, source: str | None) -> tuple[bool, str]:
        source = (source or "").strip()
        if source and source in self.channel_denylist:
            return False, "source_denied"
        if self.channel_allowlist and source not in self.channel_allowlist:
            return False, "source_not_allowed"
        return True, "ok"

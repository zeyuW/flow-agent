from __future__ import annotations

from dataclasses import dataclass, field

from infra.security.permissions import CommandPermissions


@dataclass(slots=True)
class SecurityPolicy:
    command_permissions: CommandPermissions = field(default_factory=CommandPermissions)
    channel_allowlist: set[str] = field(default_factory=set)
    channel_denylist: set[str] = field(default_factory=set)
    tool_risk_overrides: dict[str, str] = field(default_factory=dict)

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

    def check_tool_risk(self, tool_name: str, risk_level: str) -> tuple[bool, str]:
        overridden = self.tool_risk_overrides.get(tool_name, risk_level)
        if overridden == "external-side-effect":
            return False, "high_risk_tool_blocked"
        return True, "ok"

    def evaluate(
        self,
        *,
        role: str,
        action: str,
        source: str | None = None,
        tool_name: str | None = None,
        tool_risk: str = "read-only",
    ) -> tuple[bool, str]:
        allowed, reason = self.check_command(role=role, action=action)
        if not allowed:
            return allowed, reason
        allowed, reason = self.check_channel_source(source=source)
        if not allowed:
            return allowed, reason
        if tool_name:
            return self.check_tool_risk(tool_name=tool_name, risk_level=tool_risk)
        return True, "ok"

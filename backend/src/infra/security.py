"""共享认证、命令权限和安全策略基础设施。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class APIKeyAuth:
    """验证可选的 API key；未配置 key 时允许本地调用。"""

    expected_key: str | None = None

    def verify(self, provided_key: str | None) -> bool:
        if not self.expected_key:
            return True
        return bool(provided_key) and provided_key == self.expected_key


@dataclass(slots=True)
class CommandPermissions:
    """按角色判断管理命令是否允许执行。"""

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

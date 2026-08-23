"""供 Agent 调用的 Flow Skill 安装工具。"""

from typing import Any

from application.capabilities.skills.installer import SkillInstaller
from application.capabilities.tools.base import ToolResult


class InstallSkillTool:
    """只将 Git Skill 安装到 ~/.flow/skills。"""

    def __init__(self, installer: SkillInstaller) -> None:
        self._installer = installer

    @property
    def name(self) -> str:
        return "install_skill"

    @property
    def description(self) -> str:
        return "从 Git 仓库安装 Skill 到 ~/.flow/skills，不会写入其他 Agent 的目录"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repository_url": {"type": "string"},
                "names": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["repository_url"],
            "additionalProperties": False,
        }

    def run(self, tool_input: dict[str, Any]) -> ToolResult:
        repository_url = str(tool_input.get("repository_url", "")).strip()
        if not repository_url:
            return ToolResult(ok=False, content="缺少仓库地址 repository_url")
        names = [str(name) for name in tool_input.get("names", [])]
        try:
            candidates = self._installer.scan(repository_url)
            if len(candidates) > 1 and not names:
                available = "、".join(candidate.name for candidate in candidates)
                return ToolResult(
                    ok=True,
                    content=(
                        f"仓库包含多个 Skill：{available}。"
                        "请询问用户要安装哪些，或再次调用 install_skill 并传入 names。"
                    ),
                )
            selected = names or [candidates[0].name]
            installed = self._installer.install(repository_url, selected)
        except ValueError as exc:
            return ToolResult(ok=False, content=str(exc))
        installed_names = "、".join(skill.name for skill in installed)
        locations = "、".join(f"~/.flow/skills/{skill.name}" for skill in installed)
        return ToolResult(
            ok=True,
            content=f"已安装 Skill：{installed_names}。安装位置：{locations}",
        )

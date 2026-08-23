from application.capabilities.skills.installer import InstalledSkill
from application.capabilities.tools.install_skill import InstallSkillTool


class _Installer:
    def __init__(self, candidates: list[str]) -> None:
        self.candidates = candidates
        self.installed_names: list[str] = []

    def scan(self, repository_url: str):
        return [
            type("SkillCandidate", (), {"name": name})() for name in self.candidates
        ]

    def install(self, repository_url: str, names: list[str]):
        self.installed_names = names
        return [InstalledSkill(name=name) for name in names]


def test_installs_single_skill_to_flow_skill_directory():
    installer = _Installer(["design-taste-frontend"])

    result = InstallSkillTool(installer).run(
        {"repository_url": "https://github.com/Leonxlnx/taste-skill"}
    )

    assert result.ok is True
    assert installer.installed_names == ["design-taste-frontend"]
    assert "~/.flow/skills/design-taste-frontend" in result.content


def test_returns_skill_choices_for_a_multi_skill_repository():
    installer = _Installer(["code-review", "test-driven-development"])

    result = InstallSkillTool(installer).run(
        {"repository_url": "https://github.com/addyosmani/agent-skills"}
    )

    assert result.ok is True
    assert installer.installed_names == []
    assert "code-review" in result.content

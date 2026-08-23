import subprocess
from pathlib import Path

import pytest

from application.capabilities.skills.installer import SkillInstaller


def _create_skill_repository(tmp_path: Path, name: str = "daily-brief") -> Path:
    repository = tmp_path / "source"
    repository.mkdir()
    (repository / "SKILL.md").write_text(
        "---\nname: daily-brief\ndescription: 每日摘要\n---\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "SKILL.md"], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add skill"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    return repository


def test_installs_repository_with_skill_file(tmp_path: Path):
    repository = _create_skill_repository(tmp_path)
    installed_dir = tmp_path / "installed"

    installed = SkillInstaller(installed_dir).install(str(repository))

    assert installed.name == "source"
    assert (installed_dir / "source" / "SKILL.md").exists()


def test_rejects_repository_without_skill_file(tmp_path: Path):
    repository = tmp_path / "source"
    repository.mkdir()
    subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    (repository / "README.md").write_text("no skill", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repository,
        check=True,
        capture_output=True,
    )

    with pytest.raises(ValueError, match="SKILL.md"):
        SkillInstaller(tmp_path / "installed").install(str(repository))


def test_uninstalls_existing_skill(tmp_path: Path):
    installed_dir = tmp_path / "installed"
    skill_dir = installed_dir / "daily-brief"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# 每日摘要", encoding="utf-8")

    SkillInstaller(installed_dir).uninstall("daily-brief")

    assert not skill_dir.exists()


def test_scans_and_installs_selected_skills_from_skill_pack(tmp_path: Path):
    repository = tmp_path / "skill-pack"
    for name, description in [
        ("code-review", "代码审查"),
        ("test-driven-development", "测试驱动开发"),
    ]:
        skill_dir = repository / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n",
            encoding="utf-8",
        )
    subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "skills"], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add skill pack"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    installer = SkillInstaller(tmp_path / "installed")

    candidates = installer.scan(str(repository))
    installed = installer.install(str(repository), ["code-review"])

    assert [candidate.name for candidate in candidates] == [
        "code-review",
        "test-driven-development",
    ]
    assert [skill.name for skill in installed] == ["code-review"]
    assert (tmp_path / "installed" / "code-review" / "SKILL.md").exists()

from pathlib import Path

from application.capabilities.skills.catalog import SkillCatalog


def write_skill(root: Path, name: str, description: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n",
        encoding="utf-8",
    )


def test_catalog_lists_project_and_installed_skills(tmp_path: Path):
    write_skill(tmp_path / "skills", "weekly-report", "项目周报")
    write_skill(tmp_path / ".flow" / "skills", "personal-notes", "个人笔记")

    items = SkillCatalog(
        tmp_path / "builtin",
        tmp_path / "skills",
        tmp_path / ".flow" / "skills",
    ).list_items()

    assert [(item.name, item.source) for item in items] == [
        ("personal-notes", "installed"),
        ("weekly-report", "project"),
    ]
    assert {item.status for item in items} == {"available"}


def test_catalog_hides_builtin_skills_by_default(tmp_path: Path):
    write_skill(tmp_path / "builtin", "system-search", "内置搜索")

    catalog = SkillCatalog(
        tmp_path / "builtin",
        tmp_path / "skills",
        tmp_path / ".flow" / "skills",
    )

    assert catalog.list_items() == []
    assert catalog.list_items(include_builtin=True)[0].source == "builtin"


def test_catalog_marks_same_name_as_conflict(tmp_path: Path):
    write_skill(tmp_path / "skills", "report", "项目版本")
    write_skill(tmp_path / ".flow" / "skills", "report", "本机版本")

    items = SkillCatalog(
        tmp_path / "builtin",
        tmp_path / "skills",
        tmp_path / ".flow" / "skills",
    ).list_items()

    assert {item.status for item in items} == {"conflict"}
    assert {item.reason for item in items} == {"同名 Skill 冲突"}

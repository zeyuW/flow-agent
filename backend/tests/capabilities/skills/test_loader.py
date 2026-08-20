from pathlib import Path

from application.capabilities.skills.loader import SkillLoader


def test_loader_parses_yaml_frontmatter_and_dependencies(tmp_path: Path):
    skill_dir = tmp_path / "daily-news"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: daily-news\n"
        "description: 每日新闻摘要\n"
        "requires_mcp: [news, browser]\n"
        "---\n"
        "# 每日新闻\n",
        encoding="utf-8",
    )

    skill = SkillLoader(tmp_path).load()[0]

    assert skill.name == "daily-news"
    assert skill.description == "每日新闻摘要"
    assert skill.requires_mcp == ["news", "browser"]

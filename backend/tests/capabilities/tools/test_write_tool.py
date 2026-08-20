from pathlib import Path

from application.capabilities.tools.write import WriteTool


def test_write_tool_creates_nested_file(tmp_path: Path):
    path = tmp_path / "notes" / "today.md"

    result = WriteTool().run({"path": str(path), "content": "# 今天\n"})

    assert result.ok is True
    assert path.read_text(encoding="utf-8") == "# 今天\n"


def test_write_tool_maps_dot_flow_path_to_runtime_directory(tmp_path: Path):
    project_root = tmp_path / "project"
    runtime_dir = tmp_path / "user" / ".flow"

    result = WriteTool(project_root, runtime_dir).run(
        {"path": ".flow/skills/test/SKILL.md", "content": "name: test\n"}
    )

    assert result.ok is True
    assert (runtime_dir / "skills/test/SKILL.md").read_text(encoding="utf-8") == "name: test\n"
    assert not (project_root / ".flow/skills/test/SKILL.md").exists()

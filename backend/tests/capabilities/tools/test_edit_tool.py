from pathlib import Path

from application.capabilities.tools.edit import EditTool


def test_edit_tool_replaces_exactly_one_match(tmp_path: Path):
    path = tmp_path / "note.txt"
    path.write_text("before old after", encoding="utf-8")

    result = EditTool().run(
        {"path": str(path), "old_string": "old", "new_string": "new"}
    )

    assert result.ok is True
    assert path.read_text(encoding="utf-8") == "before new after"


def test_edit_tool_keeps_file_when_match_is_not_unique(tmp_path: Path):
    path = tmp_path / "note.txt"
    path.write_text("old old", encoding="utf-8")

    result = EditTool().run(
        {"path": str(path), "old_string": "old", "new_string": "new"}
    )

    assert result.ok is False
    assert path.read_text(encoding="utf-8") == "old old"

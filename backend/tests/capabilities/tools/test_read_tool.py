from pathlib import Path

from application.capabilities.tools.read import ReadTool


def test_read_tool_returns_numbered_line_range(tmp_path: Path):
    file_path = tmp_path / "hello.txt"
    file_path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    result = ReadTool().run({"path": str(file_path), "offset": 2, "limit": 1})

    assert result.ok is True
    assert result.content == "2: two\n...<continue from line 3>"


def test_read_tool_missing_path():
    result = ReadTool().run({})

    assert result.ok is False
    assert "Missing required input: path" in result.content


def test_read_tool_rejects_directory(tmp_path: Path):
    result = ReadTool().run({"path": str(tmp_path)})

    assert result.ok is False
    assert "Not a file" in result.content

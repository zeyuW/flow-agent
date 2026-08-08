from pathlib import Path

from application.capabilities.tools.filesystem import ReadFileTool


def test_read_file_tool_success(tmp_path: Path):
    file_path = tmp_path / "hello.txt"
    file_path.write_text("hello tool", encoding="utf-8")

    tool = ReadFileTool()
    result = tool.run({"path": str(file_path)})

    assert result.ok is True
    assert result.content == "hello tool"


def test_read_file_tool_missing_path():
    tool = ReadFileTool()
    result = tool.run({})

    assert result.ok is False
    assert "Missing required input: path" in result.content

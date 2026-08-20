from application.capabilities.tools.bash import BashTool


def test_bash_tool_uses_relative_working_directory(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    result = BashTool(tmp_path).run({"command": "pwd", "cwd": "work"})
    assert result.ok is True
    assert str(work) in result.content


def test_bash_tool_returns_failed_result_after_timeout(tmp_path):
    result = BashTool(tmp_path).run({"command": "sleep 1", "timeout_seconds": 0})
    assert result.ok is False
    assert "timed out" in result.content

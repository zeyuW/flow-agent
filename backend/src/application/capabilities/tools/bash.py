import subprocess
from pathlib import Path
from typing import Any

from application.capabilities.tools.base import ToolResult


class BashTool:
    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return "执行终端命令、git 或脚本 / Run a bash command."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120},
            },
            "required": ["command"],
            "additionalProperties": False,
        }

    def run(self, tool_input: dict[str, Any]) -> ToolResult:
        command = str(tool_input.get("command", "")).strip()
        if not command:
            return ToolResult(ok=False, content="Missing required input: command")
        raw_cwd = Path(str(tool_input.get("cwd", "."))).expanduser()
        cwd = raw_cwd if raw_cwd.is_absolute() else self._project_root / raw_cwd
        timeout = max(0, min(120, int(tool_input.get("timeout_seconds", 30))))
        try:
            result = subprocess.run(
                ["bash", "-lc", command],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                ok=False, content=f"Command timed out after {timeout} seconds"
            )
        except OSError as exc:
            return ToolResult(ok=False, content=f"Failed to run command: {exc}")
        content = f"exit_code: {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        content = content[:8000]
        return ToolResult(ok=result.returncode == 0, content=content)

from pathlib import Path
from typing import Any

from application.capabilities.tools.base import ToolResult
from application.capabilities.tools.path import ToolPathResolver


class EditTool:
    def __init__(self, project_root: Path | None = None, runtime_dir: Path | None = None) -> None:
        self._paths = ToolPathResolver(
            project_root or Path.cwd(), runtime_dir or Path.home() / ".flow"
        )

    @property
    def name(self) -> str:
        return "edit"

    @property
    def description(self) -> str:
        return "编辑文件并精确替换文本 / Replace one exact string in a UTF-8 text file."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
            },
            "required": ["path", "old_string", "new_string"],
            "additionalProperties": False,
        }

    def run(self, tool_input: dict[str, Any]) -> ToolResult:
        path = str(tool_input.get("path", "")).strip()
        old = tool_input.get("old_string")
        new = tool_input.get("new_string")
        if not path or not isinstance(old, str) or not isinstance(new, str):
            return ToolResult(
                ok=False,
                content="Missing required input: path, old_string or new_string",
            )
        target = self._paths.resolve(path)
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return ToolResult(ok=False, content=f"Failed to read file: {exc}")
        if content.count(old) != 1:
            return ToolResult(ok=False, content="old_string must appear exactly once")
        try:
            target.write_text(content.replace(old, new, 1), encoding="utf-8")
        except OSError as exc:
            return ToolResult(ok=False, content=f"Failed to write file: {exc}")
        return ToolResult(ok=True, content=f"Edited {target}")

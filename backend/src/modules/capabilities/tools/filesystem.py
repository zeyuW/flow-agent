from pathlib import Path
from typing import Any

from modules.capabilities.tools.base import ToolResult


class ReadFileTool:
    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "Read UTF-8 text file content by path. Input: {'path': '...'}"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative file path to read",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        }

    def run(self, tool_input: dict[str, str]) -> ToolResult:
        raw_path = tool_input.get("path", "").strip()
        if not raw_path:
            return ToolResult(ok=False, content="Missing required input: path")

        target = Path(raw_path).expanduser()
        if not target.is_absolute():
            target = Path.cwd() / target

        if not target.exists():
            return ToolResult(ok=False, content=f"File not found: {target}")
        if not target.is_file():
            return ToolResult(ok=False, content=f"Not a file: {target}")

        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ToolResult(ok=False, content=f"File is not UTF-8 text: {target}")
        except OSError as exc:
            return ToolResult(ok=False, content=f"Failed to read file: {exc}")

        if len(content) > 4000:
            content = content[:4000] + "\n...<truncated>"
        return ToolResult(ok=True, content=content)

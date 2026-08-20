from pathlib import Path
from typing import Any

from application.capabilities.tools.base import ToolResult
from application.capabilities.tools.path import ToolPathResolver


class ReadTool:
    def __init__(self, project_root: Path | None = None, runtime_dir: Path | None = None) -> None:
        self._paths = ToolPathResolver(
            project_root or Path.cwd(), runtime_dir or Path.home() / ".flow"
        )

    @property
    def name(self) -> str:
        return "read"

    @property
    def description(self) -> str:
        return "读取文件内容 / Read UTF-8 text from a file. 输入 path、可选 offset 和 limit。"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
            "additionalProperties": False,
        }

    def run(self, tool_input: dict[str, Any]) -> ToolResult:
        raw_path = str(tool_input.get("path", "")).strip()
        if not raw_path:
            return ToolResult(ok=False, content="Missing required input: path")
        target = self._paths.resolve(raw_path)
        if not target.exists():
            return ToolResult(ok=False, content=f"File not found: {target}")
        if not target.is_file():
            return ToolResult(ok=False, content=f"Not a file: {target}")
        offset = max(1, int(tool_input.get("offset", 1)))
        limit = max(1, int(tool_input.get("limit", 2000)))
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            return ToolResult(ok=False, content=f"File is not UTF-8 text: {target}")
        except OSError as exc:
            return ToolResult(ok=False, content=f"Failed to read file: {exc}")
        selected = lines[offset - 1 : offset - 1 + limit]
        content = "\n".join(
            f"{index}: {line}" for index, line in enumerate(selected, offset)
        )
        if offset - 1 + limit < len(lines):
            content += f"\n...<continue from line {offset + limit}>"
        return ToolResult(ok=True, content=content)

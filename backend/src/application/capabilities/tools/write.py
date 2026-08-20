from pathlib import Path
from typing import Any

from application.capabilities.tools.base import ToolResult
from application.capabilities.tools.path import ToolPathResolver


class WriteTool:
    def __init__(self, project_root: Path | None = None, runtime_dir: Path | None = None) -> None:
        self._paths = ToolPathResolver(
            project_root or Path.cwd(), runtime_dir or Path.home() / ".flow"
        )

    @property
    def name(self) -> str:
        return "write"

    @property
    def description(self) -> str:
        return "写入、创建或覆盖文件 / Create or overwrite a UTF-8 text file."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
            "additionalProperties": False,
        }

    def run(self, tool_input: dict[str, Any]) -> ToolResult:
        path = str(tool_input.get("path", "")).strip()
        content = tool_input.get("content")
        if not path or not isinstance(content, str):
            return ToolResult(
                ok=False, content="Missing required input: path or content"
            )
        target = self._paths.resolve(path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolResult(ok=False, content=f"Failed to write file: {exc}")
        return ToolResult(
            ok=True, content=f"Wrote {len(content)} characters to {target}"
        )

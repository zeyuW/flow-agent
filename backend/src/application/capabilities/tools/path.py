"""本地 Agent 文件工具的路径解析。"""

from pathlib import Path


class ToolPathResolver:
    """普通相对路径归属项目，`.flow/` 路径归属用户运行时目录。"""

    def __init__(self, project_root: Path, runtime_dir: Path) -> None:
        self._project_root = project_root.resolve()
        self._runtime_dir = runtime_dir.expanduser().resolve()

    def resolve(self, value: str) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        if path.parts and path.parts[0] == ".flow":
            return self._runtime_dir.joinpath(*path.parts[1:])
        return self._project_root / path

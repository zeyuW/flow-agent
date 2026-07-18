"""MCP 服务声明与工作区配置加载。"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 兼容路径
    import tomli as tomllib


@dataclass(frozen=True, slots=True)
class McpServerSpec:
    """一个 MCP stdio 服务的声明。"""

    name: str
    command: tuple[str, ...]
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    watch_paths: tuple[str, ...] = ()
    source: str = "workspace"

    def with_plugin_paths(self, plugin_dir: Path, data_dir: Path) -> "McpServerSpec":
        """把插件相对路径解析为绝对路径，并注入插件数据目录。"""
        plugin_root = plugin_dir.resolve()
        cwd = _resolve_plugin_path(plugin_root, self.cwd) if self.cwd else plugin_root
        env = {**self.env, "FLOW_PLUGIN_DATA_DIR": str(data_dir.resolve())}
        watch_paths = tuple(
            str(_resolve_plugin_path(plugin_root, value))
            for value in self.watch_paths
        )
        return replace(
            self,
            cwd=str(cwd),
            env=env,
            watch_paths=watch_paths,
        )

    def revision(self) -> str:
        """计算声明及监视路径状态的稳定修订值。"""
        digest = hashlib.sha256()
        digest.update(repr((self.name, self.command, self.cwd, sorted(self.env.items()))).encode())
        for raw_path in self.watch_paths:
            path = Path(raw_path)
            digest.update(str(path).encode())
            if not path.exists():
                digest.update(b"missing")
                continue
            if path.is_file():
                stat = path.stat()
                digest.update(f"{stat.st_mtime_ns}:{stat.st_size}".encode())
                continue
            for child in sorted(item for item in path.rglob("*") if item.is_file()):
                stat = child.stat()
                digest.update(str(child.relative_to(path)).encode())
                digest.update(f"{stat.st_mtime_ns}:{stat.st_size}".encode())
        return digest.hexdigest()


def load_workspace_mcp_specs(mcp_root: Path) -> list[McpServerSpec]:
    """从工作区的 servers/*.toml 加载并验证 MCP 声明。"""
    root = mcp_root.resolve()
    declarations = root / "servers"
    if not declarations.exists():
        return []

    specs: list[McpServerSpec] = []
    for path in sorted(declarations.glob("*.toml")):
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        schema_version = int(raw.get("schema_version", 1))
        if schema_version != 1:
            raise ValueError(f"不支持的 MCP 声明版本: {path.name}")

        name = str(raw.get("name", "")).strip()
        if not name or path.stem != name:
            raise ValueError(f"MCP 声明文件名必须与 name 一致: {path.name}")
        command = _string_tuple(raw.get("command"))
        if not command:
            raise ValueError(f"MCP 服务缺少启动命令: {name}")

        cwd = _resolve_inside(root, path.parent, raw.get("cwd"))
        watch_paths = tuple(
            str(_resolve_inside(root, path.parent, value))
            for value in _string_tuple(raw.get("watch_paths"))
        )
        env_raw = raw.get("env") or {}
        if not isinstance(env_raw, dict):
            raise ValueError(f"MCP env 必须是对象: {name}")
        env = {str(key): str(value) for key, value in env_raw.items()}

        specs.append(McpServerSpec(
            name=name,
            command=command,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            watch_paths=watch_paths,
            source=f"workspace:{path.name}",
        ))
    _ensure_unique_names(specs)
    return specs


def merge_mcp_specs(*groups: list[McpServerSpec]) -> list[McpServerSpec]:
    """合并不同来源声明，并拒绝服务名冲突。"""
    specs = [spec for group in groups for spec in group]
    _ensure_unique_names(specs)
    return specs


def _ensure_unique_names(specs: list[McpServerSpec]) -> None:
    owners: dict[str, str] = {}
    for spec in specs:
        if spec.name in owners:
            raise ValueError(
                f"MCP 服务名冲突: {spec.name} ({owners[spec.name]} / {spec.source})"
            )
        owners[spec.name] = spec.source


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list | tuple):
        raise ValueError("MCP 字段必须是字符串数组")
    return tuple(str(item).strip() for item in value if str(item).strip())


def _resolve_inside(root: Path, base: Path, value: Any) -> Path | None:
    if value is None or not str(value).strip():
        return None
    resolved = _resolve_relative_path(base, str(value))
    if not resolved.is_relative_to(root):
        raise ValueError(f"MCP 路径越出安全根目录: {value}")
    return resolved


def _resolve_relative_path(base: Path, value: str) -> Path:
    path = Path(os.path.expandvars(value)).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _resolve_plugin_path(plugin_root: Path, value: str) -> Path:
    resolved = _resolve_relative_path(plugin_root, value)
    if not resolved.is_relative_to(plugin_root):
        raise ValueError(f"插件 MCP 路径越出插件目录: {value}")
    return resolved

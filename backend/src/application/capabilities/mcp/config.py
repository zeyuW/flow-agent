"""插件声明与用户级 MCP JSON 配置。"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class McpServerSpec:
    """一个 MCP stdio 服务的完整运行声明。"""

    name: str
    command: tuple[str, ...]
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    watch_paths: tuple[str, ...] = ()
    source: str = "user"

    def with_plugin_paths(self, plugin_dir: Path, data_dir: Path) -> "McpServerSpec":
        """解析插件相对路径并注入插件私有数据目录。"""
        plugin_root = plugin_dir.resolve()
        cwd = _resolve_plugin_path(plugin_root, self.cwd) if self.cwd else plugin_root
        env = {**self.env, "FLOW_PLUGIN_DATA_DIR": str(data_dir.resolve())}
        watch_paths = tuple(
            str(_resolve_plugin_path(plugin_root, value))
            for value in self.watch_paths
        )
        return replace(self, cwd=str(cwd), env=env, watch_paths=watch_paths)

    def revision(self) -> str:
        """计算声明和监视文件状态的稳定修订值。"""
        digest = hashlib.sha256()
        digest.update(repr((
            self.name,
            self.command,
            self.url,
            sorted(self.headers.items()),
            self.cwd,
            sorted(self.env.items()),
        )).encode())
        for raw_path in self.watch_paths:
            path = Path(raw_path)
            digest.update(str(path).encode())
            if not path.exists():
                digest.update(b"missing")
            elif path.is_file():
                stat = path.stat()
                digest.update(f"{stat.st_mtime_ns}:{stat.st_size}".encode())
            else:
                for child in sorted(item for item in path.rglob("*") if item.is_file()):
                    stat = child.stat()
                    digest.update(str(child.relative_to(path)).encode())
                    digest.update(f"{stat.st_mtime_ns}:{stat.st_size}".encode())
        return digest.hexdigest()


def load_project_mcp_specs(config_path: Path) -> list[McpServerSpec]:
    """加载 ~/.flow/mcp.json 中由用户添加的外部 MCP。"""
    _ensure_project_config(config_path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if int(raw.get("schemaVersion", 1)) != 1:
        raise ValueError("不支持的项目 MCP 配置版本")
    servers = raw.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError("mcpServers 必须是对象")

    specs: list[McpServerSpec] = []
    for name, value in servers.items():
        if not isinstance(value, dict):
            raise ValueError(f"MCP 服务配置必须是对象: {name}")
        if not bool(value.get("enabled", True)):
            continue
        url = str(value.get("url", "")).strip() or None
        command_name = str(value.get("command", "")).strip()
        if not command_name and not url:
            raise ValueError(f"外部 MCP 缺少 command 或 url: {name}")
        command = (command_name, *_string_tuple(value.get("args"))) if command_name else ()
        cwd = _resolve_user_path(config_path.parent, value.get("cwd"))
        watch_paths = tuple(
            str(_resolve_user_path(config_path.parent, item))
            for item in _string_tuple(value.get("watchPaths"))
        )
        specs.append(McpServerSpec(
            name=str(name),
            command=command,
            url=url,
            headers=_string_dict(value.get("headers")),
            cwd=str(cwd) if cwd is not None else None,
            env=_string_dict(value.get("env")),
            watch_paths=watch_paths,
            source=f"project:{name}",
        ))
    _ensure_unique_names(specs)
    return specs


def load_mcp_config(config_path: Path) -> dict[str, Any]:
    """读取符合 MCP 生态的 mcpServers 配置。"""
    _ensure_project_config(config_path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or int(raw.get("schemaVersion", 1)) != 1:
        raise ValueError("不支持的 MCP 配置版本")
    servers = raw.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError("mcpServers 必须是对象")
    return raw


def save_mcp_server(
    config_path: Path,
    name: str,
    server: dict[str, Any],
) -> None:
    """原子写入一个 MCP server，避免写入过程中留下半份 JSON。"""
    name = name.strip()
    if not name:
        raise ValueError("MCP 服务名不能为空")
    if not isinstance(server, dict):
        raise ValueError("MCP 服务配置必须是对象")
    if not str(server.get("command", "")).strip() and not str(server.get("url", "")).strip():
        raise ValueError("MCP 服务缺少 command 或 url")
    raw = load_mcp_config(config_path)
    raw["mcpServers"][name] = server
    _write_mcp_config(config_path, raw)


def remove_mcp_server(config_path: Path, name: str) -> bool:
    """删除用户配置中的 MCP server。"""
    raw = load_mcp_config(config_path)
    if name not in raw["mcpServers"]:
        return False
    del raw["mcpServers"][name]
    _write_mcp_config(config_path, raw)
    return True


def set_mcp_server_enabled(config_path: Path, name: str, enabled: bool) -> bool:
    """更新 MCP server 的启用状态。"""
    raw = load_mcp_config(config_path)
    server = raw["mcpServers"].get(name)
    if not isinstance(server, dict):
        return False
    server["enabled"] = enabled
    _write_mcp_config(config_path, raw)
    return True


def merge_mcp_specs(*groups: list[McpServerSpec]) -> list[McpServerSpec]:
    """合并用户和插件声明，并拒绝全局名称冲突。"""
    specs = [spec for group in groups for spec in group]
    _ensure_unique_names(specs)
    return specs


def _ensure_project_config(config_path: Path) -> None:
    if config_path.exists():
        return
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "mcpServers": {},
    }
    temporary = config_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(config_path)


def _write_mcp_config(config_path: Path, raw: dict[str, Any]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_suffix(config_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(config_path)


def _ensure_unique_names(specs: list[McpServerSpec]) -> None:
    owners: dict[str, str] = {}
    for spec in specs:
        if spec.name in owners:
            raise ValueError(f"MCP 服务名冲突: {spec.name}")
        owners[spec.name] = spec.source


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list | tuple):
        raise ValueError("MCP 字段必须是字符串数组")
    return tuple(str(item).strip() for item in value if str(item).strip())


def _string_dict(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("MCP env 必须是对象")
    return {str(key): str(item) for key, item in value.items()}


def _resolve_user_path(base: Path, value: Any) -> Path | None:
    if value is None or not str(value).strip():
        return None
    path = Path(os.path.expandvars(str(value))).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def _resolve_plugin_path(plugin_root: Path, value: str) -> Path:
    resolved = _resolve_user_path(plugin_root, value)
    if resolved is None or not resolved.is_relative_to(plugin_root):
        raise ValueError(f"插件 MCP 路径越出插件目录: {value}")
    return resolved

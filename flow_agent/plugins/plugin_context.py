"""插件配置、私有 KV 状态和宿主资源上下文。"""

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PluginConfig:
    """合并插件默认值和 plugin-data 中的用户配置。"""

    _values: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    @classmethod
    def load(cls, plugin_dir: Path, data_dir: Path | None = None) -> "PluginConfig":
        values: dict[str, Any] = {}
        schema = _read_json(plugin_dir / "_conf_schema.json")
        if schema:
            for k, v in schema.items():
                if isinstance(v, dict):
                    values[k] = v.get("default")
                else:
                    values[k] = v
        user_root = data_dir or plugin_dir
        user = _read_json(user_root / "plugin_config.json")
        if user:
            values.update(user)
        local_toml = _read_toml(user_root / "config.local.toml")
        if local_toml:
            values.update(local_toml)
        return cls(_values=values)


@dataclass(slots=True)
class PluginKVStore:
    """由 .kv.json 支撑的插件私有持久化键值状态。"""

    _path: Path
    _data: dict[str, Any] = field(default_factory=dict)
    _lock: threading.RLock = field(
        default_factory=threading.RLock,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self._path.exists():
            self._data = _read_json(self._path) or {}

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._flush()

    def increment(self, key: str, delta: int = 1) -> int:
        with self._lock:
            val = int(self._data.get(key, 0)) + delta
            self._data[key] = val
            self._flush()
            return val

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(self._path.name + ".tmp")
        temporary.write_text(
            json.dumps(self._data, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self._path)


@dataclass(slots=True)
class PluginContext:
    """注入每个插件实例的最小宿主资源集合。"""

    event_bus: Any = None
    tool_registry: Any = None
    kv_store: PluginKVStore | None = None
    config: PluginConfig = field(default_factory=PluginConfig)
    workspace: Path | None = None
    data_dir: Path | None = None


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    raw = json.loads(path.read_text("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"插件 JSON 配置根节点必须是对象: {path}")
    return raw


def _read_toml(path: Path) -> dict | None:
    """读取插件私有 TOML 配置；语法错误由候选加载显式拒绝。"""

    if not path.exists():
        return None
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else None

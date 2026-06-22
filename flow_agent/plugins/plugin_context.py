"""PluginContext: config, KV store, and system resource injection (spec 6)."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PluginConfig:
    """Plugin config loaded from _conf_schema.json + plugin_config.json (spec 6a)."""

    _values: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    @classmethod
    def load(cls, plugin_dir: Path) -> "PluginConfig":
        values: dict[str, Any] = {}
        schema = _read_json(plugin_dir / "_conf_schema.json")
        if schema:
            for k, v in schema.items():
                if isinstance(v, dict):
                    values[k] = v.get("default")
                else:
                    values[k] = v
        user = _read_json(plugin_dir / "plugin_config.json")
        if user:
            values.update(user)
        return cls(_values=values)


@dataclass(slots=True)
class PluginKVStore:
    """Simple persistent key-value store backed by .kv.json (spec 6c)."""

    _path: Path
    _data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self._path.exists():
            self._data = _read_json(self._path) or {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._flush()

    def increment(self, key: str, delta: int = 1) -> int:
        val = int(self._data.get(key, 0)) + delta
        self._data[key] = val
        self._flush()
        return val

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, ensure_ascii=False), "utf-8")


@dataclass(slots=True)
class PluginContext:
    """System resources injected into each plugin (spec 6b)."""

    event_bus: Any = None
    tool_registry: Any = None
    kv_store: PluginKVStore | None = None
    config: PluginConfig = field(default_factory=PluginConfig)
    workspace: Path | None = None


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

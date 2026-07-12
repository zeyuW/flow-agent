from __future__ import annotations

from pathlib import Path
from typing import Any


class ConfigValues:
    """统一配置访问：仅从 config.toml 读取，不再使用环境变量。"""

    def __init__(
        self,
        *,
        external_config: dict[str, object],
        project_root: Path,
    ) -> None:
        self.external_config = external_config
        self.project_root = project_root

    def deep_get(self, *keys: str) -> Any:
        current: object = self.external_config
        for key in keys:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    def _from_external(self, path: tuple[str, ...]) -> Any:
        return self.deep_get(*path) if path else None

    @staticmethod
    def _to_bool(value: str, default: bool) -> bool:
        if value == "":
            return default
        return value.lower() not in {"0", "false", "no", "off"}

    @staticmethod
    def split_csv(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    def get_str(self, path: tuple[str, ...], default: str) -> str:
        # 仅从 config.toml 读取
        external = self._from_external(path)
        return str(external if external not in {None, ""} else default)

    def get_bool(self, path: tuple[str, ...], default: bool) -> bool:
        # 仅从 config.toml 读取
        external = self._from_external(path)
        if external is None:
            return default
        if isinstance(external, bool):
            return external
        return self._to_bool(str(external), default)

    def get_int(
        self,
        path: tuple[str, ...],
        default: int,
        *,
        minimum: int | None = None,
    ) -> int:
        # 仅从 config.toml 读取
        raw = self._from_external(path)
        value = int(default if raw in {None, ""} else raw)
        return max(minimum, value) if minimum is not None else value

    def get_float(
        self,
        path: tuple[str, ...],
        default: float,
        *,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> float:
        # 仅从 config.toml 读取
        raw = self._from_external(path)
        value = float(default if raw in {None, ""} else raw)
        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return value

    def get_csv(self, path: tuple[str, ...], default: list[str] | None = None) -> list[str]:
        # 仅从 config.toml 读取
        external = self._from_external(path)
        if external is None:
            return list(default or [])
        if isinstance(external, list):
            return [str(item) for item in external if str(item).strip()]
        return self.split_csv(str(external))

    def env_str(self, key: str, default: str) -> str:
        # 不再支持环境变量，返回默认值
        return default

    def env_bool(self, key: str, default: bool) -> bool:
        # 不再支持环境变量，返回默认值
        return default

    def env_int(self, key: str, default: int, minimum: int | None = None) -> int:
        # 不再支持环境变量，返回默认值
        return max(minimum, default) if minimum is not None else default

    def env_float(self, key: str, default: float, minimum: float | None = None) -> float:
        # 不再支持环境变量，返回默认值
        return max(minimum, default) if minimum is not None else default

    def prefixed_bool(self, path: tuple[str, ...], default: bool) -> bool:
        # 仅从 config.toml 读取
        external_default = self.deep_get(*path)
        fallback = bool(external_default) if external_default is not None else default
        return fallback

    def prefixed_str(self, path: tuple[str, ...], default: str) -> str:
        # 仅从 config.toml 读取
        return str(self.deep_get(*path) or default)

    def prefixed_int(
        self,
        path: tuple[str, ...],
        default: int,
        minimum: int | None = None,
    ) -> int:
        # 仅从 config.toml 读取
        value = int(self.deep_get(*path) or str(default))
        return max(minimum, value) if minimum is not None else value

    def prefixed_float(
        self,
        path: tuple[str, ...],
        default: float,
        minimum: float | None = None,
    ) -> float:
        # 仅从 config.toml 读取
        value = float(self.deep_get(*path) or str(default))
        return max(minimum, value) if minimum is not None else value

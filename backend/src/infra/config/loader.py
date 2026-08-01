from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from infra.config.schema import AppConfig


def load_config(path: Path) -> AppConfig:
    """读取唯一 TOML 配置源并返回完整不可变快照。"""

    with path.open("rb") as config_file:
        raw: dict[str, Any] = tomllib.load(config_file)
    return AppConfig.model_validate(raw)

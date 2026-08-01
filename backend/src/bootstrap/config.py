from pathlib import Path

from infra.config.loader import load_config
from infra.config.schema import AppConfig


def load_application_config(backend_root: Path) -> AppConfig:
    """从后端根目录加载唯一运行配置。"""

    return load_config(backend_root / "config.toml")

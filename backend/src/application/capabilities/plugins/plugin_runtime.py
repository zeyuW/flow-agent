"""插件源码运行时支持。

本模块负责计算插件修订、动态导入隔离包和清理模块；插件能力发布由
``plugin_loader.py`` 负责。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import ModuleType

from application.capabilities.plugins.plugin_base import Plugin


def plugin_revision(plugin_dir: Path, data_dir: Path | None) -> str:
    """计算插件代码、声明和用户配置文件的稳定修订。"""

    digest = hashlib.sha256()
    paths = list(plugin_dir.rglob("*"))
    if data_dir is not None:
        paths.extend(
            path
            for name in ("plugin_config.json", "config.local.toml")
            if (path := data_dir / name).exists()
        )
    for path in sorted(paths, key=lambda item: str(item)):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix.lower() not in {".py", ".json", ".toml", ".yaml", ".yml"}:
            continue
        try:
            relative = path.relative_to(plugin_dir)
        except ValueError:
            relative = Path("plugin-data") / path.name
        digest.update(str(relative).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def import_module(filepath: Path, package_name: str, plugin_dir: Path):
    """建立独立包并直接编译源码，支持相对导入且不复用旧字节码。"""

    package = ModuleType(package_name)
    package.__path__ = [str(plugin_dir)]
    package.__package__ = package_name
    sys.modules[package_name] = package
    module_name = f"{package_name}.plugin"
    module = ModuleType(module_name)
    module.__file__ = str(filepath)
    module.__package__ = package_name
    sys.modules[module_name] = module
    source = filepath.read_text(encoding="utf-8")
    exec(compile(source, str(filepath), "exec"), module.__dict__)
    return module


def discard_modules(package_name: str) -> None:
    """移除一个插件代际包及其相对导入的全部子模块。"""

    for name in [
        item
        for item in sys.modules
        if item == package_name or item.startswith(package_name + ".")
    ]:
        sys.modules.pop(name, None)


def find_plugin_class(module) -> type[Plugin] | None:
    """从动态模块中找到唯一的 Plugin 子类。"""

    for value in vars(module).values():
        if isinstance(value, type) and issubclass(value, Plugin) and value is not Plugin:
            return value
    return None

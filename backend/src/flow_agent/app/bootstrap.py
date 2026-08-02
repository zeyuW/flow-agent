"""旧应用组装入口转发层。"""

from importlib import import_module


def __getattr__(name: str):
    """按需解析新组装入口，避免旧包在静态依赖图中反向依赖 bootstrap。"""
    return getattr(import_module("bootstrap.container"), name)

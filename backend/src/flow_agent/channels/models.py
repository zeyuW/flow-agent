"""渠道消息模型旧路径转发层。"""

from importlib import import_module


def __getattr__(name: str):
    """按需解析接口层模型，避免旧包静态依赖接口实现。"""
    return getattr(import_module("interfaces.channels.models"), name)

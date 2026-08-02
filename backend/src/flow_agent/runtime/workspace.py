"""工作区布局旧路径转发层。"""

from importlib import import_module

from infra.runtime.workspace import *


def init_workspace(root):
    """兼容旧入口，转交给启动层完成业务目录初始化。"""
    return import_module("bootstrap.workspace").init_workspace(root)


def __getattr__(name: str):
    """按需解析启动初始化逻辑，避免旧包静态依赖组合根。"""
    if name == "init_workspace":
        return getattr(import_module("bootstrap.workspace"), name)
    return getattr(import_module("infra.runtime.workspace"), name)

"""应用启动阶段的工作区初始化编排。"""

from pathlib import Path

from infra.lifecycle.workspace import (
    WorkspaceLayout,
    detect_workspace,
    init_workspace as _init_workspace,
    persist_workspace_profile,
)

__all__ = [
    "WorkspaceLayout",
    "detect_workspace",
    "init_workspace",
    "persist_workspace_profile",
]


def init_workspace(root: Path) -> WorkspaceLayout:
    """创建基础工作区，并初始化需要业务目录的模块。"""

    layout = _init_workspace(root)
    from application.memory.markdown_store import MarkdownStore
    from application.proactive.infra.gate import ProactiveStateStore

    MarkdownStore(layout.memory_dir).initialize()
    ProactiveStateStore(layout.proactive_state_db).close()
    return layout

"""应用启动阶段的工作区初始化编排。"""

from pathlib import Path

from infra.runtime.workspace import WorkspaceLayout, init_workspace as _init_workspace


def init_workspace(root: Path) -> WorkspaceLayout:
    """创建基础工作区，并初始化需要业务目录的模块。"""

    layout = _init_workspace(root)
    from modules.memory.markdown_store import MarkdownStore
    from modules.proactive.infra.gate import ProactiveStateStore

    MarkdownStore(layout.memory_dir).initialize()
    ProactiveStateStore(layout.proactive_state_db).close()
    return layout

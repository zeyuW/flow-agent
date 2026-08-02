"""工作区布局的旧路径转发层。"""

from pathlib import Path

from infra.runtime.workspace import *
from infra.runtime.workspace import init_workspace as _init_workspace


def init_workspace(root: Path):
    """兼容旧入口，完成记忆和主动状态的业务初始化。"""

    layout = _init_workspace(root)
    from modules.memory.markdown_store import MarkdownStore
    from modules.proactive.infra.gate import ProactiveStateStore

    MarkdownStore(layout.memory_dir).initialize()
    ProactiveStateStore(layout.proactive_state_db).close()
    return layout

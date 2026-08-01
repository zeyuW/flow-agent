from pathlib import Path

from flow_agent.runtime.workspace import build_layout


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_LAYOUT = build_layout(PROJECT_ROOT)
FLOW_DIR = WORKSPACE_LAYOUT.flow_dir
DATA_DIR = WORKSPACE_LAYOUT.data_dir


def get_memory_db_path() -> Path:
    """返回统一布局中的主数据库路径。"""

    return WORKSPACE_LAYOUT.memory_db

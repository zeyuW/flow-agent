"""共享工作区布局、初始化、发现和进程锁基础设施。

本模块集中管理 ``.flow`` 目录下的运行时路径，以及保证同一工作区只启动
一个服务进程的文件锁。业务模块通过这里获取路径，不自行拼接运行时目录。
"""

from __future__ import annotations

import fcntl
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

WORKSPACE_MARKER = ".workspace"
WORKSPACE_VERSION = "flow-agent-workspace-v2"
FLOW_DIR = ".flow"


@dataclass(slots=True)
class WorkspaceLayout:
    root: Path
    flow_dir: Path
    data_dir: Path
    memory_dir: Path
    memory_journal_dir: Path
    memory_consolidation_db: Path
    project_skills_dir: Path
    installed_skills_dir: Path
    drift_dir: Path
    drift_skills_dir: Path
    plugins_dir: Path
    plugin_data_dir: Path
    sessions_dir: Path
    logs_dir: Path
    attachments_dir: Path
    inbound_attachments_dir: Path
    outbound_attachments_dir: Path
    memory_db: Path
    memory_vectors_db: Path
    embedding_cache_file: Path
    proactive_state_db: Path
    background_jobs_db: Path
    outbound_messages_db: Path
    drift_state_db: Path
    scheduled_tasks_db: Path
    trace_file: Path
    proactive_trace_file: Path
    app_log_file: Path
    mcp_dir: Path
    mcp_config_file: Path
    subagent_tasks_file: Path
    drift_history_file: Path
    marker_file: Path


def build_layout(root: Path, *, runtime_dir: Path | None = None) -> WorkspaceLayout:
    """根据项目根目录构建完整运行时路径，不产生文件系统副作用。"""

    root = root.resolve()
    flow = (runtime_dir or Path.home() / FLOW_DIR).expanduser().resolve()
    data = flow / "data"
    memory = flow / "memory"
    drift = flow / "drift"
    sessions = flow / "sessions"
    logs = flow / "logs"
    attachments = flow / "attachments"
    return WorkspaceLayout(
        root=root,
        flow_dir=flow,
        data_dir=data,
        memory_dir=memory,
        memory_journal_dir=memory / "journal",
        memory_consolidation_db=memory / "consolidation_writes.db",
        project_skills_dir=root / "skills",
        installed_skills_dir=flow / "skills",
        drift_dir=drift,
        drift_skills_dir=drift / "skills",
        plugins_dir=flow / "plugins",
        plugin_data_dir=flow / "plugin-data",
        sessions_dir=sessions,
        logs_dir=logs,
        attachments_dir=attachments,
        inbound_attachments_dir=attachments / "inbound",
        outbound_attachments_dir=attachments / "outbound",
        memory_db=data / "memory.db",
        memory_vectors_db=data / "memory_vectors.db",
        embedding_cache_file=data / "embedding_cache.json",
        proactive_state_db=data / "proactive.db",
        background_jobs_db=data / "background_jobs.db",
        outbound_messages_db=data / "outbound_messages.db",
        drift_state_db=drift / "drift.db",
        scheduled_tasks_db=data / "scheduled_tasks.db",
        trace_file=logs / "trace.jsonl",
        proactive_trace_file=logs / "proactive.jsonl",
        app_log_file=logs / "app.log",
        mcp_dir=flow / "mcp",
        mcp_config_file=flow / "mcp.json",
        subagent_tasks_file=sessions / "subagent_tasks.jsonl",
        drift_history_file=drift / "drift.json",
        marker_file=flow / WORKSPACE_MARKER,
    )


def init_workspace(root: Path, *, runtime_dir: Path | None = None) -> WorkspaceLayout:
    """初始化不包含业务副作用的运行时工作区。"""

    layout = build_layout(root, runtime_dir=runtime_dir)
    for folder in _workspace_directories(layout):
        folder.mkdir(parents=True, exist_ok=True)

    for file_path, content in _workspace_files(layout):
        if not file_path.exists():
            file_path.write_text(content, encoding="utf-8")

    layout.marker_file.write_text(WORKSPACE_VERSION + "\n", encoding="utf-8")
    return layout


def _workspace_directories(layout: WorkspaceLayout) -> tuple[Path, ...]:
    """返回初始化时必须存在的目录集合。"""

    return (
        layout.data_dir,
        layout.memory_dir,
        layout.memory_journal_dir,
        layout.project_skills_dir,
        layout.installed_skills_dir,
        layout.drift_skills_dir,
        layout.plugins_dir,
        layout.plugin_data_dir,
        layout.sessions_dir,
        layout.logs_dir,
        layout.mcp_dir,
        layout.inbound_attachments_dir,
        layout.outbound_attachments_dir,
    )


def _workspace_files(layout: WorkspaceLayout) -> tuple[tuple[Path, str], ...]:
    """返回可安全预创建的文本和 JSON 文件。"""

    return (
        (
            layout.project_skills_dir / "README.md",
            "# 项目技能\n\n每个技能目录包含 SKILL.md，可选 scripts、references、assets。本目录应提交到 Git。\n",
        ),
        (
            layout.installed_skills_dir / "README.md",
            "# 已安装技能\n\n每个技能目录包含 SKILL.md，可选 scripts、references、assets。本目录是本机运行时数据，不应提交到 Git。\n",
        ),
        (
            layout.drift_skills_dir / "README.md",
            "# 漂移技能\n\n每个技能目录至少包含 skill.json；SKILL.md 描述执行流程，state.json 由运行时维护。\n",
        ),
        (
            layout.plugins_dir / "README.md",
            "# 插件\n\n每个插件目录以 plugin.py 声明工具、MCP 服务和主动信息源；用户配置与状态应写入 plugin-data。\n",
        ),
        (
            layout.plugin_data_dir / "README.md",
            "# 插件私有数据\n\n按插件名称保存 plugin_config.json、.kv.json 和缓存，不与插件程序文件混放。\n",
        ),
        (layout.embedding_cache_file, "{}\n"),
        (layout.subagent_tasks_file, ""),
        (layout.drift_history_file, '{"recent_runs": []}\n'),
        (layout.trace_file, ""),
        (layout.proactive_trace_file, ""),
        (layout.app_log_file, ""),
        (layout.mcp_config_file, '{"schemaVersion": 1, "mcpServers": {}}\n'),
    )


def detect_workspace(
    start: Path | None = None, *, runtime_dir: Path | None = None
) -> WorkspaceLayout | None:
    current = (start or Path.cwd()).resolve()
    for path in (current, *current.parents):
        if (path / "skills").is_dir():
            return build_layout(path, runtime_dir=runtime_dir)
    return None


def require_workspace(start: Path | None = None) -> WorkspaceLayout:
    layout = detect_workspace(start)
    if layout is None:
        raise RuntimeError("工作区尚未初始化，请先运行 flow-agent init。")
    return layout


def apply_workspace_env(layout: WorkspaceLayout) -> None:
    """为仍使用环境变量的外部集成提供统一路径。"""

    os.environ.setdefault("FLOW_AGENT_MEMORY_DB_PATH", str(layout.memory_db))
    os.environ.setdefault("FLOW_AGENT_TRACE_PATH", str(layout.trace_file))
    os.environ.setdefault("FLOW_AGENT_SKILLS_DIR", str(layout.installed_skills_dir))
    os.environ.setdefault(
        "FLOW_AGENT_SUBAGENT_TASKS_FILE", str(layout.subagent_tasks_file)
    )


def persist_workspace_profile(layout: WorkspaceLayout, profile: str) -> None:
    """已废弃：运行配置只从项目根目录的 config.toml 读取。"""

    del layout, profile


# 供仍需固定项目根目录的基础设施和启动入口使用的全局布局。
PROJECT_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_LAYOUT = build_layout(PROJECT_ROOT)
DATA_DIR = WORKSPACE_LAYOUT.data_dir


def get_memory_db_path() -> Path:
    """返回统一布局中的主数据库路径。"""

    return WORKSPACE_LAYOUT.memory_db


class WorkspaceAlreadyRunningError(RuntimeError):
    """同一工作区已经有运行实例。"""


class WorkspaceProcessLock:
    """使用内核文件锁保护工作区运行时所有权。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: TextIO | None = None

    def acquire(self) -> None:
        """非阻塞获取锁，并写入当前进程号。"""

        if self._handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.seek(0)
            owner = handle.read().strip() or "unknown"
            handle.close()
            raise WorkspaceAlreadyRunningError(
                f"工作区已有运行实例: pid={owner}"
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        os.fsync(handle.fileno())
        self._handle = handle

    def release(self) -> None:
        """释放工作区所有权；残留锁文件不会阻止下次启动。"""

        handle = self._handle
        if handle is None:
            return
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._handle = None

    def __enter__(self) -> "WorkspaceProcessLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()

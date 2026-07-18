from __future__ import annotations

import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path


WORKSPACE_MARKER = ".workspace"
WORKSPACE_VERSION = "flow-agent-workspace-v2"
FLOW_DIR = ".flow"


@dataclass(slots=True)
class WorkspaceLayout:
    root: Path
    flow_dir: Path
    data_dir: Path
    memory_dir: Path
    skills_dir: Path
    drift_dir: Path
    drift_skills_dir: Path
    plugins_dir: Path
    plugin_data_dir: Path
    mcp_dir: Path
    sources_dir: Path
    rss_sources_dir: Path
    snapshot_sources_dir: Path
    sessions_dir: Path
    logs_dir: Path
    attachments_dir: Path
    inbound_attachments_dir: Path
    outbound_attachments_dir: Path
    memory_db: Path
    memory_vectors_db: Path
    embedding_cache_file: Path
    proactive_state_db: Path
    trace_file: Path
    proactive_trace_file: Path
    app_log_file: Path
    mcp_servers_file: Path
    proactive_source_file: Path
    proactive_todo_file: Path
    proactive_tasks_file: Path
    subagent_tasks_file: Path
    drift_history_file: Path
    marker_file: Path


def build_layout(root: Path) -> WorkspaceLayout:
    """根据项目根目录构建完整运行时路径，不产生文件系统副作用。"""

    root = root.resolve()
    flow = root / FLOW_DIR
    data = flow / "data"
    memory = flow / "memory"
    drift = flow / "drift"
    sources = flow / "sources"
    sessions = flow / "sessions"
    logs = flow / "logs"
    attachments = flow / "attachments"
    return WorkspaceLayout(
        root=root,
        flow_dir=flow,
        data_dir=data,
        memory_dir=memory,
        skills_dir=flow / "skills",
        drift_dir=drift,
        drift_skills_dir=drift / "skills",
        plugins_dir=flow / "plugins",
        plugin_data_dir=flow / "plugin-data",
        mcp_dir=flow / "mcp",
        sources_dir=sources,
        rss_sources_dir=sources / "rss",
        snapshot_sources_dir=sources / "snapshots",
        sessions_dir=sessions,
        logs_dir=logs,
        attachments_dir=attachments,
        inbound_attachments_dir=attachments / "inbound",
        outbound_attachments_dir=attachments / "outbound",
        memory_db=data / "memory.db",
        memory_vectors_db=data / "memory_vectors.db",
        embedding_cache_file=data / "embedding_cache.json",
        proactive_state_db=data / "proactive.db",
        trace_file=logs / "trace.jsonl",
        proactive_trace_file=logs / "proactive.jsonl",
        app_log_file=logs / "app.log",
        mcp_servers_file=flow / "mcp" / "servers.json",
        proactive_source_file=sources / "proactive_items.txt",
        proactive_todo_file=sources / "todo_items.txt",
        proactive_tasks_file=sources / "tasks.txt",
        subagent_tasks_file=sessions / "subagent_tasks.jsonl",
        drift_history_file=drift / "drift.json",
        marker_file=flow / WORKSPACE_MARKER,
    )


def init_workspace(root: Path) -> WorkspaceLayout:
    """初始化运行时工作区，并把旧版根层数据安全迁移到分类目录。"""

    layout = build_layout(root)
    previous_version = _read_text(layout.marker_file)
    for folder in _workspace_directories(layout):
        folder.mkdir(parents=True, exist_ok=True)

    if previous_version.strip() not in {WORKSPACE_VERSION}:
        _migrate_legacy_layout(layout)

    for file_path, content in _workspace_files(layout):
        if not file_path.exists():
            file_path.write_text(content, encoding="utf-8")

    from flow_agent.memory.markdown_store import MarkdownStore
    from flow_agent.proactive.gate import ProactiveStateStore

    MarkdownStore(layout.memory_dir).initialize()
    ProactiveStateStore(layout.proactive_state_db).close()

    layout.marker_file.write_text(WORKSPACE_VERSION + "\n", encoding="utf-8")
    return layout


def _workspace_directories(layout: WorkspaceLayout) -> tuple[Path, ...]:
    """返回初始化时必须存在的目录集合。"""

    return (
        layout.data_dir,
        layout.memory_dir,
        layout.skills_dir,
        layout.drift_skills_dir,
        layout.plugins_dir,
        layout.plugin_data_dir,
        layout.mcp_dir,
        layout.sources_dir,
        layout.rss_sources_dir,
        layout.snapshot_sources_dir,
        layout.sessions_dir,
        layout.logs_dir,
        layout.inbound_attachments_dir,
        layout.outbound_attachments_dir,
    )


def _workspace_files(layout: WorkspaceLayout) -> tuple[tuple[Path, str], ...]:
    """返回可安全预创建的文本和 JSON 文件。"""

    return (
        (
            layout.proactive_source_file,
            "# 一行一个主动候选，空行和井号开头的行会被忽略\n",
        ),
        (
            layout.proactive_todo_file,
            "# 一行一个待办事项，空行和井号开头的行会被忽略\n",
        ),
        (
            layout.proactive_tasks_file,
            "# 一行一个任务，空行和井号开头的行会被忽略\n",
        ),
        (
            layout.skills_dir / "README.md",
            "# 普通技能\n\n每个技能目录建议同时包含 skill.json 和 SKILL.md，可选 scripts、references、assets。\n",
        ),
        (
            layout.drift_skills_dir / "README.md",
            "# 漂移技能\n\n每个技能目录至少包含 skill.json；SKILL.md 描述执行流程，state.json 由运行时维护。\n",
        ),
        (
            layout.plugins_dir / "README.md",
            "# 插件\n\n每个插件目录包含 plugin.py 和 plugin.json；用户配置与状态应写入 plugin-data。\n",
        ),
        (
            layout.plugin_data_dir / "README.md",
            "# 插件私有数据\n\n按插件名称保存 plugin_config.json、.kv.json 和缓存，不与插件程序文件混放。\n",
        ),
        (
            layout.sources_dir / "README.md",
            "# 主动数据源\n\nproactive_items.txt、tasks.txt、todo_items.txt 均为一行一项；rss 放 XML，snapshots 放文本快照。\n",
        ),
        (layout.embedding_cache_file, "{}\n"),
        (layout.mcp_servers_file, '{"servers": {}}\n'),
        (layout.subagent_tasks_file, ""),
        (layout.drift_history_file, '{"recent_runs": []}\n'),
        (layout.trace_file, ""),
        (layout.proactive_trace_file, ""),
        (layout.app_log_file, ""),
    )


def _migrate_legacy_layout(layout: WorkspaceLayout) -> None:
    """迁移旧版根层文件；目标已有有效内容时不覆盖。"""

    flow = layout.flow_dir
    _migrate_sqlite(flow / "memory.db", layout.memory_db)
    _migrate_sqlite(flow / "memory_vectors.db", layout.memory_vectors_db)
    _merge_json_object(flow / "embedding_cache.json", layout.embedding_cache_file)
    _merge_json_object(flow / "mcp_servers.json", layout.mcp_servers_file)
    _merge_jsonl(flow / "trace.jsonl", layout.trace_file)
    _merge_jsonl(flow / "subagent_tasks.jsonl", layout.subagent_tasks_file)


def _migrate_sqlite(source: Path, target: Path) -> None:
    """使用 SQLite backup 迁移数据库，确保 WAL 中的已提交数据也被复制。"""

    if not source.is_file() or source.stat().st_size == 0:
        return
    if target.is_file() and target.stat().st_size > 0:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    try:
        with sqlite3.connect(str(source)) as source_db:
            with sqlite3.connect(str(target)) as target_db:
                source_db.backup(target_db)
    except sqlite3.DatabaseError:
        shutil.copy2(source, target)


def _merge_json_object(source: Path, target: Path) -> None:
    """合并 JSON 对象，目标文件中的同名键优先。"""

    source_data = _read_json_object(source)
    if not source_data:
        return
    target_data = _read_json_object(target)
    merged = {**source_data, **target_data}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _merge_jsonl(source: Path, target: Path) -> None:
    """按完整行去重合并 JSONL，避免重复启动造成重复迁移。"""

    if not source.is_file():
        return
    source_lines = [
        line for line in source.read_text(encoding="utf-8").splitlines() if line
    ]
    if not source_lines:
        return
    target_lines = (
        [
            line
            for line in target.read_text(encoding="utf-8").splitlines()
            if line
        ]
        if target.is_file()
        else []
    )
    known = set(target_lines)
    merged = list(target_lines)
    for line in source_lines:
        if line not in known:
            merged.append(line)
            known.add(line)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(merged) + "\n", encoding="utf-8")


def _read_json_object(path: Path) -> dict:
    """读取 JSON 对象，文件不存在或格式错误时返回空对象。"""

    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_text(path: Path) -> str:
    """读取可选文本文件。"""

    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def detect_workspace(start: Path | None = None) -> WorkspaceLayout | None:
    current = (start or Path.cwd()).resolve()
    for path in (current, *current.parents):
        new_marker = path / FLOW_DIR / WORKSPACE_MARKER
        if new_marker.exists():
            return build_layout(path)
        legacy_marker = path / WORKSPACE_MARKER
        if legacy_marker.exists():
            return build_layout(path)
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
    os.environ.setdefault("FLOW_AGENT_SKILLS_DIR", str(layout.skills_dir))
    os.environ.setdefault("FLOW_AGENT_PROACTIVE_SOURCE_FILE", str(layout.proactive_source_file))
    os.environ.setdefault("FLOW_AGENT_PROACTIVE_TODO_FILE", str(layout.proactive_todo_file))
    os.environ.setdefault("FLOW_AGENT_PROACTIVE_TASKS_FILE", str(layout.proactive_tasks_file))
    os.environ.setdefault("FLOW_AGENT_SUBAGENT_TASKS_FILE", str(layout.subagent_tasks_file))


def persist_workspace_profile(layout: WorkspaceLayout, profile: str) -> None:
    """已废弃：运行配置只从项目根目录的 config.toml 读取。"""

    del layout, profile

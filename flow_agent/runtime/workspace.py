from __future__ import annotations

import os
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
    memory_journal_dir: Path
    memory_consolidation_db: Path
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
        memory_journal_dir=memory / "journal",
        memory_consolidation_db=memory / "consolidation_writes.db",
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
    """初始化当前版本的运行时工作区。"""

    layout = build_layout(root)
    for folder in _workspace_directories(layout):
        folder.mkdir(parents=True, exist_ok=True)

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
        layout.memory_journal_dir,
        layout.skills_dir,
        layout.drift_skills_dir,
        layout.plugins_dir,
        layout.plugin_data_dir,
        layout.mcp_dir,
        layout.mcp_dir / "servers",
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
            "# 插件\n\n每个插件目录以 plugin.py 声明工具、MCP 服务和主动信息源；用户配置与状态应写入 plugin-data。\n",
        ),
        (
            layout.plugin_data_dir / "README.md",
            "# 插件私有数据\n\n按插件名称保存 plugin_config.json、.kv.json 和缓存，不与插件程序文件混放。\n",
        ),
        (
            layout.mcp_dir / "servers" / "README.md",
            "# MCP 服务声明\n\n每个 TOML 文件声明一个 stdio MCP 服务，文件名必须与 name 一致。\n",
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


def detect_workspace(start: Path | None = None) -> WorkspaceLayout | None:
    current = (start or Path.cwd()).resolve()
    for path in (current, *current.parents):
        new_marker = path / FLOW_DIR / WORKSPACE_MARKER
        if new_marker.exists():
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

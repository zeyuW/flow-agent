from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


WORKSPACE_MARKER = ".workspace"
FLOW_DIR = ".flow"


@dataclass(slots=True)
class WorkspaceLayout:
    root: Path
    flow_dir: Path
    data_dir: Path
    skills_dir: Path
    plugins_dir: Path
    sources_dir: Path
    sessions_dir: Path
    logs_dir: Path
    memory_db: Path
    trace_file: Path
    proactive_source_file: Path
    proactive_todo_file: Path
    proactive_tasks_file: Path
    subagent_tasks_file: Path
    marker_file: Path


def build_layout(root: Path) -> WorkspaceLayout:
    root = root.resolve()
    flow = root / FLOW_DIR
    return WorkspaceLayout(
        root=root,
        flow_dir=flow,
        data_dir=flow / "data",
        skills_dir=flow / "skills",
        plugins_dir=flow / "plugins",
        sources_dir=flow / "sources",
        sessions_dir=flow / "sessions",
        logs_dir=flow / "logs",
        memory_db=flow / "data" / "memory.db",
        trace_file=flow / "logs" / "trace.jsonl",
        proactive_source_file=flow / "sources" / "proactive_items.txt",
        proactive_todo_file=flow / "sources" / "todo_items.txt",
        proactive_tasks_file=flow / "sources" / "tasks.txt",
        subagent_tasks_file=flow / "sessions" / "subagent_tasks.jsonl",
        marker_file=flow / WORKSPACE_MARKER,
    )


def init_workspace(root: Path) -> WorkspaceLayout:
    layout = build_layout(root)
    for folder in (
        layout.data_dir,
        layout.skills_dir,
        layout.plugins_dir,
        layout.sources_dir,
        layout.sessions_dir,
        layout.logs_dir,
    ):
        folder.mkdir(parents=True, exist_ok=True)
    for file_path, content in (
        (layout.proactive_source_file, "# proactive items\n"),
        (layout.proactive_todo_file, "# todo items\n"),
        (layout.proactive_tasks_file, "# proactive tasks\n"),
    ):
        if not file_path.exists():
            file_path.write_text(content, encoding="utf-8")
    if not layout.marker_file.exists():
        layout.marker_file.write_text("flow-agent-workspace-v1\n", encoding="utf-8")
    return layout


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
        raise RuntimeError("workspace not initialized. run `flow-agent init` first.")
    return layout


def apply_workspace_env(layout: WorkspaceLayout) -> None:
    os.environ.setdefault("FLOW_AGENT_MEMORY_DB_PATH", str(layout.memory_db))
    os.environ.setdefault("FLOW_AGENT_TRACE_PATH", str(layout.trace_file))
    os.environ.setdefault("FLOW_AGENT_SKILLS_DIR", str(layout.skills_dir))
    os.environ.setdefault("FLOW_AGENT_PROACTIVE_SOURCE_FILE", str(layout.proactive_source_file))
    os.environ.setdefault("FLOW_AGENT_PROACTIVE_TODO_FILE", str(layout.proactive_todo_file))
    os.environ.setdefault("FLOW_AGENT_PROACTIVE_TASKS_FILE", str(layout.proactive_tasks_file))
    os.environ.setdefault("FLOW_AGENT_SUBAGENT_TASKS_FILE", str(layout.subagent_tasks_file))


def persist_workspace_profile(layout: WorkspaceLayout, profile: str) -> None:
    """已废弃：config 目录已移除，profile 仅通过 .env 配置。"""
    pass

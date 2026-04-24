from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


WORKSPACE_MARKER = ".workspace"


@dataclass(slots=True)
class WorkspaceLayout:
    root: Path
    config_dir: Path
    data_dir: Path
    skills_dir: Path
    plugins_dir: Path
    sources_dir: Path
    sessions_dir: Path
    logs_dir: Path
    config_file: Path
    memory_db: Path
    trace_file: Path
    proactive_source_file: Path
    proactive_todo_file: Path
    proactive_tasks_file: Path
    subagent_tasks_file: Path
    marker_file: Path


def build_layout(root: Path) -> WorkspaceLayout:
    root = root.resolve()
    return WorkspaceLayout(
        root=root,
        config_dir=root / "config",
        data_dir=root / "data",
        skills_dir=root / "skills",
        plugins_dir=root / "plugins",
        sources_dir=root / "sources",
        sessions_dir=root / "sessions",
        logs_dir=root / "logs",
        config_file=root / "config" / "flow-agent.toml",
        memory_db=root / "data" / "memory.db",
        trace_file=root / "logs" / "trace.jsonl",
        proactive_source_file=root / "sources" / "proactive_items.txt",
        proactive_todo_file=root / "sources" / "todo_items.txt",
        proactive_tasks_file=root / "sources" / "tasks.txt",
        subagent_tasks_file=root / "sessions" / "subagent_tasks.jsonl",
        marker_file=root / WORKSPACE_MARKER,
    )


def init_workspace(root: Path) -> WorkspaceLayout:
    layout = build_layout(root)
    for folder in (
        layout.config_dir,
        layout.data_dir,
        layout.skills_dir,
        layout.plugins_dir,
        layout.sources_dir,
        layout.sessions_dir,
        layout.logs_dir,
    ):
        folder.mkdir(parents=True, exist_ok=True)
    if not layout.config_file.exists():
        layout.config_file.write_text(_default_toml(), encoding="utf-8")
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
        marker = path / WORKSPACE_MARKER
        if marker.exists():
            return build_layout(path)
    return None


def require_workspace(start: Path | None = None) -> WorkspaceLayout:
    layout = detect_workspace(start)
    if layout is None:
        raise RuntimeError("workspace not initialized. run `flow-agent init` first.")
    return layout


def apply_workspace_env(layout: WorkspaceLayout) -> None:
    os.environ.setdefault("FLOW_AGENT_CONFIG_FILE", str(layout.config_file))
    os.environ.setdefault("FLOW_AGENT_MEMORY_DB_PATH", str(layout.memory_db))
    os.environ.setdefault("FLOW_AGENT_TRACE_PATH", str(layout.trace_file))
    os.environ.setdefault("FLOW_AGENT_SKILLS_DIR", str(layout.skills_dir))
    os.environ.setdefault("FLOW_AGENT_PROACTIVE_SOURCE_FILE", str(layout.proactive_source_file))
    os.environ.setdefault("FLOW_AGENT_PROACTIVE_TODO_FILE", str(layout.proactive_todo_file))
    os.environ.setdefault("FLOW_AGENT_PROACTIVE_TASKS_FILE", str(layout.proactive_tasks_file))
    os.environ.setdefault("FLOW_AGENT_SUBAGENT_TASKS_FILE", str(layout.subagent_tasks_file))


def persist_workspace_profile(layout: WorkspaceLayout, profile: str) -> None:
    normalized = profile.strip().lower() or "dev"
    if normalized not in {"dev", "prod"}:
        raise ValueError(f"unsupported profile: {profile}")
    if not layout.config_file.exists():
        layout.config_file.write_text(_default_toml(), encoding="utf-8")
    content = layout.config_file.read_text(encoding="utf-8")
    lines = content.splitlines()
    in_governance = False
    updated = False
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_governance and not updated:
                new_lines.append(f'profile = "{normalized}"')
                updated = True
            in_governance = stripped == "[governance]"
            new_lines.append(line)
            continue
        if in_governance and stripped.startswith("profile"):
            new_lines.append(f'profile = "{normalized}"')
            updated = True
            continue
        new_lines.append(line)
    if not updated:
        if not any(item.strip() == "[governance]" for item in lines):
            new_lines = [*new_lines, "", "[governance]", 'config_version = "v1"']
        new_lines.append(f'profile = "{normalized}"')
    layout.config_file.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")


def _default_toml() -> str:
    return (
        "[governance]\n"
        'config_version = "v1"\n'
        'profile = "dev"\n\n'
        "[channels]\n"
        "cli_enabled = true\n"
        "http_enabled = false\n"
        "dashboard_enabled = false\n"
        'http_host = "127.0.0.1"\n'
        "http_port = 8788\n"
        'dashboard_host = "127.0.0.1"\n'
        "dashboard_port = 8787\n\n"
        "[jobs]\n"
        "max_async_queue = 64\n"
        "timeout_seconds = 30\n"
    )

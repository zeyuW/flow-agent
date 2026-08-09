"""应用层目录和依赖方向约束。"""

from __future__ import annotations

import ast
from pathlib import Path

APPLICATION_ROOT = Path(__file__).parents[2] / "src" / "application"
BOOTSTRAP_ROOT = Path(__file__).parents[2] / "src" / "bootstrap"


def _application_graph() -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {}
    for path in APPLICATION_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(APPLICATION_ROOT)
        if not relative.parts:
            continue
        owner = relative.parts[0]
        graph.setdefault(owner, set())
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module]
            else:
                continue
            for name in imported:
                if not name.startswith("application."):
                    continue
                target = name.split(".")[1]
                if target != owner:
                    graph[owner].add(target)
    return graph


def _cycles(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    active: list[str] = []
    completed: set[str] = set()
    found: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        if node in active:
            found.append(tuple(active[active.index(node) :] + [node]))
            return
        if node in completed:
            return
        active.append(node)
        for dependency in sorted(graph.get(node, ())):
            visit(dependency)
        active.pop()
        completed.add(node)

    for node in sorted(graph):
        visit(node)
    return found


def test_application_uses_the_new_semantic_directories() -> None:
    expected = {
        "agent",
        "passive",
        "proactive",
        "schedule",
        "automation",
        "delegation",
        "memory",
        "capabilities",
    }
    assert expected <= {
        path.name for path in APPLICATION_ROOT.iterdir() if path.is_dir()
    }
    assert not any(
        (APPLICATION_ROOT / old_name).exists()
        for old_name in ("conversation", "tasks", "scheduling")
    )
    assert not (BOOTSTRAP_ROOT / "workspace.py").exists()


def test_application_dependency_graph_has_no_cycles() -> None:
    assert _cycles(_application_graph()) == []

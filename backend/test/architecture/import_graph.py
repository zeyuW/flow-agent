from __future__ import annotations

import ast
from pathlib import Path

ImportGraph = dict[str, set[str]]


def build_import_graph(source_root: Path, package_roots: set[str]) -> ImportGraph:
    """构建源码根目录内指定包之间的静态导入图。"""

    modules = _discover_modules(source_root, package_roots)
    graph: ImportGraph = {module: set() for module in modules}
    for source, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for imported in _imported_names(source, path, node):
                target = _resolve_module(imported, modules)
                if target is not None and target != source:
                    graph[source].add(target)
    return graph


def find_import_cycles(graph: ImportGraph) -> list[tuple[str, ...]]:
    """使用强连通分量返回稳定排序后的多模块导入环。"""

    index = 0
    indices: dict[str, int] = {}
    low_links: dict[str, int] = {}
    stack: list[str] = []
    stacked: set[str] = set()
    cycles: list[tuple[str, ...]] = []

    def visit(module: str) -> None:
        nonlocal index
        indices[module] = index
        low_links[module] = index
        index += 1
        stack.append(module)
        stacked.add(module)

        for target in sorted(graph.get(module, ())):
            if target not in indices:
                visit(target)
                low_links[module] = min(low_links[module], low_links[target])
            elif target in stacked:
                low_links[module] = min(low_links[module], indices[target])

        if low_links[module] != indices[module]:
            return
        component: list[str] = []
        while stack:
            target = stack.pop()
            stacked.remove(target)
            component.append(target)
            if target == module:
                break
        if len(component) > 1:
            cycles.append(tuple(sorted(component)))

    for module in sorted(graph):
        if module not in indices:
            visit(module)
    return sorted(cycles)


def _discover_modules(
    source_root: Path,
    package_roots: set[str],
) -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in sorted(source_root.rglob("*.py")):
        relative = path.relative_to(source_root)
        if not relative.parts or relative.parts[0] not in package_roots:
            continue
        parts = list(relative.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        if parts:
            modules[".".join(parts)] = path
    return modules


def _imported_names(source: str, path: Path, node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if not isinstance(node, ast.ImportFrom):
        return ()

    base = _resolve_from_import(source, path, node)
    if base is None:
        return ()
    imported = tuple(
        f"{base}.{alias.name}" for alias in node.names if alias.name != "*"
    )
    if node.module is None:
        return imported
    return (base, *imported)


def _resolve_from_import(
    source: str,
    path: Path,
    node: ast.ImportFrom,
) -> str | None:
    if node.level == 0:
        return node.module

    package_parts = source.split(".")
    if path.name != "__init__.py":
        package_parts.pop()
    ascent = node.level - 1
    if ascent > len(package_parts):
        return None
    if ascent:
        package_parts = package_parts[:-ascent]
    if node.module:
        package_parts.extend(node.module.split("."))
    return ".".join(package_parts) or None


def _resolve_module(imported: str, modules: dict[str, Path]) -> str | None:
    parts = imported.split(".")
    while parts:
        candidate = ".".join(parts)
        if candidate in modules:
            return candidate
        parts.pop()
    return None

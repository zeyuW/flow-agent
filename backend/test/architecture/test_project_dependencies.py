from pathlib import Path

from .import_graph import build_import_graph, find_import_cycles

BACKEND_ROOT = Path(__file__).parents[2]
SOURCE_ROOT = BACKEND_ROOT / "src"
PACKAGE_ROOTS = {"modules", "interfaces", "infra", "bootstrap"}


def graph() -> dict[str, set[str]]:
    return build_import_graph(SOURCE_ROOT, PACKAGE_ROOTS)


def layer_of(module: str) -> tuple[str | None, str | None]:
    parts = module.split(".")
    if len(parts) < 3 or parts[0] != "modules":
        return None, None
    module_name = parts[1]
    layer = parts[2] if parts[2] in {"domain", "application", "infra"} else None
    return module_name, layer


def test_project_import_graph_has_no_cycles():
    assert find_import_cycles(graph()) == []


def test_module_layer_dependencies_are_one_way():
    violations: list[tuple[str, str]] = []
    for source, targets in graph().items():
        source_module, source_layer = layer_of(source)
        for target in targets:
            target_module, target_layer = layer_of(target)
            if source_layer == "domain" and target_layer in {"application", "infra"}:
                violations.append((source, target))
            if source.startswith("modules.") and target.startswith(
                ("interfaces.", "bootstrap.")
            ):
                violations.append((source, target))
    assert sorted(set(violations)) == []


def test_shared_infrastructure_has_no_business_dependency():
    violations = [
        (source, target)
        for source, targets in graph().items()
        if source.startswith("infra.")
        for target in targets
        if target.startswith(("modules.", "interfaces.", "bootstrap."))
    ]
    assert sorted(violations) == []

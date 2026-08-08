from pathlib import Path

from .import_graph import build_import_graph, find_import_cycles

BACKEND_ROOT = Path(__file__).parents[2]
SOURCE_ROOT = BACKEND_ROOT / "src"
PACKAGE_ROOTS = {"application", "interfaces", "infra", "bootstrap"}


def graph() -> dict[str, set[str]]:
    return build_import_graph(SOURCE_ROOT, PACKAGE_ROOTS)


def layer_of(module: str) -> tuple[str | None, str | None]:
    parts = module.split(".")
    if len(parts) < 3 or parts[0] != "application":
        return None, None
    module_name = parts[1]
    layer = parts[2] if parts[2] in {"domain", "app", "infra"} else None
    return module_name, layer


def test_project_import_graph_has_no_cycles():
    assert find_import_cycles(graph()) == []


def test_module_layer_dependencies_are_one_way():
    violations: list[tuple[str, str]] = []
    for source, targets in graph().items():
        source_module, source_layer = layer_of(source)
        for target in targets:
            target_module, target_layer = layer_of(target)
            if source_layer == "domain" and target_layer in {"app", "infra"}:
                violations.append((source, target))
            if source.startswith("application.") and target.startswith(
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
        if target.startswith(("application.", "interfaces.", "bootstrap."))
    ]
    assert sorted(violations) == []


def test_tool_adapters_are_flattened_into_tools_boundary():
    """工具适配器没有额外职责时直接放在 tools 边界下。"""

    tools_root = SOURCE_ROOT / "application" / "capabilities" / "tools"
    adapters_root = tools_root / "adapters"
    assert not any(adapters_root.glob("*.py"))
    for filename in ("filesystem.py", "mcp_manage.py", "undo.py"):
        assert (tools_root / filename).exists()


def test_bus_is_the_single_top_level_bus_namespace():
    """事件总线和消息总线共享 bus 命名空间。"""

    bus_root = SOURCE_ROOT / "infra" / "bus"
    legacy_root = SOURCE_ROOT / "infra" / "messagebus"
    assert (bus_root / "message.py").exists()
    assert (bus_root / "event.py").exists()
    assert not any(legacy_root.glob("*.py"))


def test_message_bus_is_the_single_reliable_transport():
    """可靠消息传输统一归于 infra.bus.MessageBus。"""

    bus_root = SOURCE_ROOT / "infra" / "bus"
    assert (bus_root / "message.py").exists()
    assert not (SOURCE_ROOT / "application" / "delivery").exists()


def test_bus_adapters_use_role_names_instead_of_legacy_names():
    """总线适配器按职责命名，不保留迁移期 legacy 前缀。"""

    conversation_infra = SOURCE_ROOT / "application" / "conversation" / "infra"
    assert (SOURCE_ROOT / "infra" / "bus" / "types.py").exists()
    assert not (SOURCE_ROOT / "application" / "ports").exists()
    assert not (conversation_infra / "inbound_source.py").exists()
    assert not (conversation_infra / "legacy_message_bus.py").exists()


def test_worker_manager_uses_accurate_lifecycle_name():
    """后台常驻线程管理器不使用暗示故障恢复的 Supervisor 名称。"""

    worker_root = SOURCE_ROOT / "infra"
    assert (worker_root / "worker.py").exists()
    assert not (worker_root / "supervisor.py").exists()

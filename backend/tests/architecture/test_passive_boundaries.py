"""被动对话模块的职责边界。"""

from __future__ import annotations

import ast
from pathlib import Path

PASSIVE_ROOT = Path(__file__).parents[2] / "src" / "application" / "passive"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_passive_application_has_cohesive_flow_components() -> None:
    app_root = PASSIVE_ROOT / "app"
    assert (app_root / "prompt.py").exists()
    assert (app_root / "reasoning.py").exists()
    assert (app_root / "delivery.py").exists()


def test_pipeline_is_orchestration_only() -> None:
    source = (PASSIVE_ROOT / "app" / "pipeline.py").read_text(encoding="utf-8")
    assert "class PromptRenderer" not in source
    assert "class PassiveReasoner" not in source
    assert "class PassiveTurnDelivery" not in source
    assert "def _run_tool_loop" not in source


def test_passive_app_helpers_do_not_depend_on_private_session_adapters() -> None:
    for name in ("prompt.py", "reasoning.py", "delivery.py"):
        imports = _imports(PASSIVE_ROOT / "app" / name)
        assert not any(name.startswith("application.passive.infra") for name in imports)


def test_conversation_context_is_kept_with_session_runtime() -> None:
    session_manager = PASSIVE_ROOT / "infra" / "session_manager.py"
    assert "class ConversationContext" in session_manager.read_text(encoding="utf-8")
    assert not (PASSIVE_ROOT / "infra" / "context.py").exists()

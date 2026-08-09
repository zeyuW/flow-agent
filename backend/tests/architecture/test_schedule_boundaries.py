"""schedule 业务模块的分层边界。"""

from __future__ import annotations

import ast
from pathlib import Path


SCHEDULE_ROOT = Path(__file__).parents[2] / "src" / "application" / "schedule"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_schedule_has_explicit_domain_and_infra_modules() -> None:
    assert (SCHEDULE_ROOT / "domain" / "models.py").exists()
    assert (SCHEDULE_ROOT / "infra" / "store.py").exists()


def test_schedule_domain_does_not_depend_on_application_or_infrastructure() -> None:
    imports = _imports(SCHEDULE_ROOT / "domain" / "models.py")
    assert not any(
        name.startswith(("application.", "infra.", "interfaces."))
        for name in imports
    )


def test_schedule_infra_does_not_depend_on_application_app() -> None:
    imports = _imports(SCHEDULE_ROOT / "infra" / "store.py")
    assert not any(name.startswith("application.schedule.app") for name in imports)

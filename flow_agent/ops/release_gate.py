from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class GateResult:
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    details: dict[str, str] = field(default_factory=dict)


def run_release_gate(project_root: Path) -> GateResult:
    checks: dict[str, bool] = {}
    details: dict[str, str] = {}

    tests_dir = project_root / "tests"
    required_tests = [
        "test_pipeline.py",
        "test_retriever.py",
        "test_proactive_tick.py",
        "test_stage19_security_marketplace.py",
    ]
    missing = [name for name in required_tests if not (tests_dir / name).exists()]
    checks["required_tests_present"] = not missing
    details["required_tests_present"] = "ok" if not missing else f"missing={','.join(missing)}"

    config_dev = project_root / "config" / "dev.toml"
    config_prod = project_root / "config" / "prod.toml"
    checks["config_files_present"] = config_dev.exists() and config_prod.exists()
    details["config_files_present"] = "ok" if checks["config_files_present"] else "missing dev/prod config"

    stage_doc = project_root / "stage.md"
    checks["stage_doc_present"] = stage_doc.exists()
    details["stage_doc_present"] = "ok" if stage_doc.exists() else "missing stage.md"

    return GateResult(
        passed=all(checks.values()),
        checks=checks,
        details=details,
    )

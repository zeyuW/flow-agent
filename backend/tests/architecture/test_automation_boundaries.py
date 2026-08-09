"""自动化作业模块的职责边界。"""

from __future__ import annotations

from pathlib import Path


AUTOMATION_ROOT = Path(__file__).parents[2] / "src" / "application" / "automation"


def test_automation_has_a_separate_execution_component() -> None:
    assert (AUTOMATION_ROOT / "app" / "executor.py").exists()


def test_runtime_only_owns_trigger_and_lifecycle_orchestration() -> None:
    source = (AUTOMATION_ROOT / "app" / "runtime.py").read_text(encoding="utf-8")
    assert "class AutomationExecutor" not in source
    assert "retry_call(" not in source
    assert "def _is_debounced" not in source


def test_automation_domain_does_not_depend_on_runtime_or_storage() -> None:
    source = (AUTOMATION_ROOT / "domain" / "models.py").read_text(encoding="utf-8")
    assert "application.automation.app" not in source
    assert "application.automation.infra" not in source


def test_automation_job_contract_belongs_to_automation_domain() -> None:
    domain_source = (AUTOMATION_ROOT / "domain" / "models.py").read_text(
        encoding="utf-8"
    )
    plugin_models = (
        AUTOMATION_ROOT.parent / "capabilities" / "plugins" / "models.py"
    ).read_text(encoding="utf-8")

    assert "class JobSpec" in domain_source
    assert "application.capabilities.plugins" not in domain_source
    assert "class JobSpec" not in plugin_models

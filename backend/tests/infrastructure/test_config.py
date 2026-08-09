from pathlib import Path
from inspect import signature
from types import SimpleNamespace

import pytest

from bootstrap.config import load_application_config
from bootstrap.container import (
    _RuntimeConfigApplier,
    create_app_runtime,
    create_core_components,
)
from infra.config import AppConfig


def test_bootstrap_loads_only_backend_config(tmp_path: Path):
    (tmp_path / "config.toml").write_text(
        '[llm.main]\nmodel="main-model"\napi_key="secret"\n',
        encoding="utf-8",
    )

    config = load_application_config(tmp_path)

    assert config.llm.main.model == "main-model"


def test_bootstrap_does_not_search_parent_directories(tmp_path: Path):
    (tmp_path / "config.toml").write_text(
        '[llm.main]\nmodel="parent-model"\napi_key="secret"\n',
        encoding="utf-8",
    )
    backend_root = tmp_path / "backend"
    backend_root.mkdir()

    with pytest.raises(FileNotFoundError):
        load_application_config(backend_root)


def test_bootstrap_anchors_runtime_paths_to_project_root(tmp_path: Path):
    (tmp_path / "config.toml").write_text(
        """
[llm.main]
model = "main-model"
api_key = "secret"

[storage]
memory_db_path = ".flow/data/custom-memory.db"

[proactive]
state_path = ".flow/data/custom-proactive.db"
""",
        encoding="utf-8",
    )

    config = load_application_config(tmp_path)

    assert config.storage.memory_db_path == str(
        tmp_path / ".flow/data/custom-memory.db"
    )
    assert config.proactive.state_path == str(
        tmp_path / ".flow/data/custom-proactive.db"
    )


def test_runtime_composition_requires_explicit_config():
    core_parameter = signature(create_core_components).parameters["config"]
    runtime_parameter = signature(create_app_runtime).parameters["config"]

    assert core_parameter.default is core_parameter.empty
    assert runtime_parameter.default is runtime_parameter.empty


def app_config() -> AppConfig:
    return AppConfig.model_validate(
        {"llm": {"main": {"model": "main", "api_key": "secret"}}}
    )


def test_runtime_config_applier_commits_only_reloadable_values():
    background = SimpleNamespace(shutdown_timeout_seconds=30.0)
    pipeline = SimpleNamespace(max_tool_steps=5, tool_selection_max=8)
    mcp = SimpleNamespace(startup_timeout=30.0, call_timeout=60.0)
    applier = _RuntimeConfigApplier(
        proactive_loop=None,
        proactive_target="",
        proactive_state=object(),
        pipeline=pipeline,
        automation_runtime=background,
        mcp_registry=mcp,
    )
    current = app_config()
    candidate = current.model_copy(
        update={
            "jobs": current.jobs.model_copy(update={"timeout_seconds": 12.0}),
            "tooling": current.tooling.model_copy(update={"max_tool_steps": 3}),
        }
    )

    prepared = applier.prepare(current, candidate)

    assert background.shutdown_timeout_seconds == 30.0
    prepared.commit()
    assert background.shutdown_timeout_seconds == 12.0
    assert pipeline.max_tool_steps == 3


def test_runtime_config_applier_rejects_restart_required_changes():
    applier = _RuntimeConfigApplier(
        proactive_loop=None,
        proactive_target="",
        proactive_state=object(),
        pipeline=SimpleNamespace(max_tool_steps=5, tool_selection_max=8),
        automation_runtime=SimpleNamespace(shutdown_timeout_seconds=30.0),
        mcp_registry=SimpleNamespace(startup_timeout=30.0, call_timeout=60.0),
    )
    current = app_config()
    candidate = current.model_copy(
        update={
            "llm": current.llm.model_copy(
                update={"main": current.llm.main.model_copy(update={"model": "other"})}
            )
        }
    )

    with pytest.raises(ValueError, match="重启"):
        applier.prepare(current, candidate)

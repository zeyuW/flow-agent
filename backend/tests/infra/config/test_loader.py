from pathlib import Path

import pytest
from pydantic import ValidationError

from infra.config.loader import load_config


def test_load_config_maps_toml_directly(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[llm.main]\nmodel="main-model"\napi_key="secret"\n'
        "[jobs]\nmax_async_workers=3\n",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.llm.main.model == "main-model"
    assert config.jobs.max_async_workers == 3


def test_load_config_does_not_read_environment(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FLOW_AGENT_LLM_MAIN_API_KEY", "environment-secret")
    path = tmp_path / "config.toml"
    path.write_text('[llm.main]\nmodel="main-model"\n', encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(path)


def test_load_config_does_not_search_for_another_file(tmp_path: Path):
    (tmp_path / "config.toml").write_text(
        '[llm.main]\nmodel="main-model"\napi_key="secret"\n',
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.toml")

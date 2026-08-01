import time
from pathlib import Path
from types import SimpleNamespace

from flow_agent.config.watcher import ConfigWatcher


def test_config_watcher_commits_valid_candidate(monkeypatch, tmp_path: Path):
    config = tmp_path / "config.toml"
    config.write_text("value = 1\n", encoding="utf-8")
    applied = []
    monkeypatch.setattr(
        "flow_agent.config.watcher.load_settings",
        lambda force_reload=False: SimpleNamespace(value=2),
    )
    watcher = ConfigWatcher(config, applied.append, interval_seconds=0.2)
    watcher.start()
    config.write_text("value = 222\n", encoding="utf-8")
    try:
        deadline = time.time() + 2
        while not applied and time.time() < deadline:
            time.sleep(0.05)
    finally:
        watcher.stop()

    assert applied and applied[0].value == 2


def test_config_watcher_restores_previous_snapshot_when_commit_fails(
    monkeypatch,
    tmp_path: Path,
):
    config = tmp_path / "config.toml"
    config.write_text("value = 1\n", encoding="utf-8")
    previous = SimpleNamespace(value=1)
    candidate = SimpleNamespace(value=2)
    calls = iter((previous, candidate))
    restored = []
    monkeypatch.setattr(
        "flow_agent.config.watcher.load_settings",
        lambda force_reload=False: next(calls),
    )
    monkeypatch.setattr(
        "flow_agent.config.watcher.replace_settings_cache",
        restored.append,
    )
    watcher = ConfigWatcher(
        config,
        lambda settings: (_ for _ in ()).throw(RuntimeError("提交失败")),
        interval_seconds=0.2,
    )
    watcher.start()
    config.write_text("value = 222\n", encoding="utf-8")
    try:
        deadline = time.time() + 2
        while not restored and time.time() < deadline:
            time.sleep(0.05)
    finally:
        watcher.stop()

    assert restored == [previous]

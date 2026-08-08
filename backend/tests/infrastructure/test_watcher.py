from pathlib import Path
import threading

from infra.config import AppConfig, ConfigWatchLoop, ConfigWatcher, PreparedConfigChange


def config(model: str) -> AppConfig:
    return AppConfig.model_validate(
        {"llm": {"main": {"model": model, "api_key": "secret"}}}
    )


def test_prepare_failure_discards_candidates_and_keeps_current(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("revision-one", encoding="utf-8")
    actions: list[str] = []

    class PreparedApplier:
        def __init__(self, name: str) -> None:
            self.name = name

        def prepare(self, current: AppConfig, candidate: AppConfig):
            return PreparedConfigChange(
                commit=lambda: actions.append("commit"),
                discard=lambda: actions.append(f"discard:{self.name}"),
            )

    class FailingApplier:
        def prepare(self, current: AppConfig, candidate: AppConfig):
            raise ValueError("运行时更新无效")

    old = config("old")
    watcher = ConfigWatcher(
        path,
        current=old,
        appliers=(PreparedApplier("one"), PreparedApplier("two"), FailingApplier()),
        loader=lambda _: config("new"),
    )
    path.write_text("revision-two", encoding="utf-8")

    assert watcher.reload_once() is False
    assert actions == ["discard:two", "discard:one"]
    assert watcher.current is old


def test_success_commits_in_prepare_order_and_updates_snapshot(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("revision-one", encoding="utf-8")
    actions: list[str] = []

    class Applier:
        def __init__(self, name: str) -> None:
            self.name = name

        def prepare(self, current: AppConfig, candidate: AppConfig):
            actions.append(f"prepare:{self.name}")
            return PreparedConfigChange(
                commit=lambda: actions.append(f"commit:{self.name}"),
                discard=lambda: actions.append(f"discard:{self.name}"),
            )

    candidate = config("new")
    watcher = ConfigWatcher(
        path,
        current=config("old"),
        appliers=(Applier("one"), Applier("two")),
        loader=lambda _: candidate,
    )
    path.write_text("revision-two", encoding="utf-8")

    assert watcher.reload_once() is True
    assert actions == ["prepare:one", "prepare:two", "commit:one", "commit:two"]
    assert watcher.current is candidate


def test_unchanged_revision_is_not_loaded_again(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("revision-one", encoding="utf-8")
    loads: list[Path] = []

    def loader(candidate_path: Path) -> AppConfig:
        loads.append(candidate_path)
        return config("new")

    watcher = ConfigWatcher(path, current=config("old"), appliers=(), loader=loader)

    assert watcher.reload_once() is False
    assert watcher.reload_once() is False
    assert loads == []


def test_invalid_revision_is_attempted_only_once(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("revision-one", encoding="utf-8")
    attempts = 0

    def loader(_: Path) -> AppConfig:
        nonlocal attempts
        attempts += 1
        raise ValueError("配置无效")

    watcher = ConfigWatcher(path, current=config("old"), appliers=(), loader=loader)
    path.write_text("revision-two", encoding="utf-8")

    assert watcher.reload_once() is False
    assert watcher.reload_once() is False
    assert attempts == 1


def test_watch_loop_starts_and_stops_polling():
    reloaded = threading.Event()

    class Watcher:
        def reload_once(self) -> bool:
            reloaded.set()
            return True

    loop = ConfigWatchLoop(Watcher(), interval_seconds=0.01)

    loop.start()
    assert reloaded.wait(timeout=0.5)
    loop.stop()
    assert loop.is_running is False

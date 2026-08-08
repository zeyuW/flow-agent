"""ServiceApp 应用生命周期测试。"""

import threading
import time


def test_wait_blocks_until_service_stop_event_is_set():
    """wait 应保持主线程阻塞，直到应用收到停止信号。"""

    from bootstrap.service_app import ServiceApp

    app = ServiceApp.__new__(ServiceApp)
    app._stop_event = threading.Event()
    finished = threading.Event()

    def wait_for_app() -> None:
        app.wait()
        finished.set()

    waiter = threading.Thread(target=wait_for_app, daemon=True)
    waiter.start()
    time.sleep(0.02)
    assert finished.is_set() is False

    app._stop_event.set()
    waiter.join(timeout=0.5)

    assert finished.is_set() is True


def test_main_calls_app_lifecycle_in_order(monkeypatch):
    """main 应保证 init、start、wait、stop 的调用顺序。"""

    import bootstrap.main as entrypoint

    calls: list[str] = []

    class FakeApp:
        def __init__(self, config) -> None:
            assert config == "config"

        def init(self) -> None:
            calls.append("init")

        def start(self) -> None:
            calls.append("start")

        def wait(self) -> None:
            calls.append("wait")
            raise KeyboardInterrupt

        def stop(self) -> None:
            calls.append("stop")

    monkeypatch.setattr(entrypoint, "load_application_config", lambda _: "config")
    monkeypatch.setattr(entrypoint, "ServiceApp", FakeApp)

    entrypoint.main()

    assert calls == ["init", "start", "wait", "stop"]

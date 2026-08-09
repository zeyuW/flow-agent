"""ServiceApp 应用生命周期测试。"""

import threading
import time
import asyncio
from types import SimpleNamespace
from typing import Any


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


def test_stop_continues_cleanup_when_one_resource_fails():
    """单个资源停止失败时，其他资源和线程仍必须继续回收。"""

    from bootstrap.service_app import ServiceApp

    app = ServiceApp.__new__(ServiceApp)
    app._state = "running"
    app._lifecycle_lock = threading.RLock()
    app._stop_event = threading.Event()
    app._lock_owned = False
    app._threads = []
    app._dispatch_loop_holder = {}
    calls: list[str] = []
    typed_app: Any = app

    class FailingChannels:
        def stop_all(self):
            calls.append("channels.stop")
            raise RuntimeError("telegram stop failed")

        def join_all(self, timeout=None):
            del timeout
            calls.append("channels.join")

    class Resource:
        def __init__(self, name):
            self.name = name

        def stop(self):
            calls.append(self.name)

        def request_stop(self):
            calls.append(self.name)

        def stop_background(self):
            calls.append(self.name)

        def shutdown(self):
            calls.append(self.name)

        def stop_all(self):
            calls.append(self.name)

    class PluginManager:
        async def shutdown_all(self):
            calls.append("plugins.stop")

    typed_app._channel_service = FailingChannels()
    typed_app._proactive_runtime = Resource("proactive.stop")
    typed_app._memory_optimizer_loop = Resource("memory.stop")
    typed_app._passive_loop = Resource("passive.stop")
    typed_app._automation_runtime = Resource("automation.stop")
    typed_app._subagent_runtime = SimpleNamespace(manager=Resource("subagent.stop"))
    typed_app._plugin_manager = PluginManager()
    typed_app._mcp_registry = Resource("mcp.stop")
    typed_app._memory_runtime = SimpleNamespace(event_executor=None)
    typed_app._message_bus = None

    app.stop()

    assert app.state == "stopped"
    assert calls == [
        "channels.stop",
        "proactive.stop",
        "memory.stop",
        "passive.stop",
        "automation.stop",
        "subagent.stop",
        "plugins.stop",
        "mcp.stop",
        "channels.join",
    ]


def test_stop_dispatch_waits_for_dispatch_loop_to_be_ready():
    """停止竞态中应等待分发事件循环就绪后再提交停止协程。"""

    from bootstrap.service_app import ServiceApp

    app = ServiceApp.__new__(ServiceApp)
    app._dispatch_loop_holder = {}
    app._dispatch_ready = threading.Event()
    calls: list[str] = []
    release = threading.Event()
    loop_ready = threading.Event()
    typed_app: Any = app

    class MessageBus:
        async def stop_dispatch_task(self) -> None:
            calls.append("dispatch.stop")
            asyncio.get_running_loop().call_soon(asyncio.get_running_loop().stop)

    typed_app._message_bus = MessageBus()

    def dispatch_thread() -> None:
        release.wait(timeout=1.0)
        loop = asyncio.new_event_loop()
        app._dispatch_loop_holder["loop"] = loop
        app._dispatch_ready.set()
        loop_ready.set()
        asyncio.set_event_loop(loop)
        # 真实 MessageBus 的分发任务会周期性轮询队列；保持测试 loop
        # 有周期性调度，避免把跨线程停止误测成空闲 loop 唤醒问题。
        def tick() -> None:
            loop.call_later(0.01, tick)

        loop.call_soon(tick)
        loop.run_forever()
        loop.close()

    worker = threading.Thread(target=dispatch_thread, daemon=True)
    worker.start()
    finished = threading.Event()

    def stop_dispatch() -> None:
        app._stop_dispatch()
        finished.set()

    stopper = threading.Thread(target=stop_dispatch)
    stopper.start()
    time.sleep(0.02)
    assert finished.is_set() is False

    release.set()
    assert loop_ready.wait(timeout=1.0)
    stopper.join(timeout=1.0)
    worker.join(timeout=1.0)

    assert finished.is_set() is True
    assert calls == ["dispatch.stop"]


def test_stop_continues_cleanup_when_ctrl_c_interrupts_a_resource():
    """Ctrl+C 打断一个停止动作时，其他资源仍必须继续回收。"""

    from bootstrap.service_app import ServiceApp

    app = ServiceApp.__new__(ServiceApp)
    app._state = "running"
    app._lifecycle_lock = threading.RLock()
    app._stop_event = threading.Event()
    app._lock_owned = False
    app._threads = []
    app._dispatch_loop_holder = {}
    app._message_bus = None
    calls: list[str] = []
    typed_app: Any = app

    class Channels:
        def stop_all(self):
            calls.append("channels.stop")
            raise KeyboardInterrupt

        def join_all(self, timeout=None):
            del timeout
            calls.append("channels.join")

    class Resource:
        def stop_all(self):
            calls.append("mcp.stop")

    typed_app._channel_service = Channels()
    typed_app._proactive_runtime = None
    typed_app._memory_optimizer_loop = None
    typed_app._passive_loop = None
    typed_app._automation_runtime = None
    typed_app._subagent_runtime = None
    typed_app._plugin_manager = None
    typed_app._mcp_registry = Resource()
    typed_app._memory_runtime = SimpleNamespace(event_executor=None)

    app.stop()

    assert app.state == "stopped"
    assert calls == ["channels.stop", "mcp.stop", "channels.join"]

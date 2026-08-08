"""Flow Agent 应用生命周期。"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path

from application.capabilities.tools.message_push import MessagePushTool
from application.capabilities.mcp.server_registry import McpServerRegistry
from application.conversation.app.chat_worker import ChatWorker
from application.memory.app.maintenance import MemoryOptimizerLoop
from application.proactive.app.loop import ProactiveLoop
from application.tasks.app.runtime import BackgroundRuntime
from bootstrap.container import create_app_runtime
from infra.config import AppConfig
from infra.workspace import WORKSPACE_LAYOUT
from infra.workspace import (
    WorkspaceAlreadyRunningError,
    WorkspaceProcessLock,
)
from infra.bus.event import EventBus
from infra.bus.message import MessageBus
from interfaces.channels.http import HTTPChannel
from interfaces.channels.protocol import ChannelContext
from interfaces.channels.telegram import TelegramChannel

logger = logging.getLogger(__name__)


class ServiceApp:
    """管理整个进程内服务的初始化、启动、等待和停止。"""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._state = "new"
        self._lifecycle_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._lock = WorkspaceProcessLock(WORKSPACE_LAYOUT.flow_dir / "runtime.lock")
        self._lock_owned = False

        self._threads: list[threading.Thread] = []
        self._telegram_loop_holder: dict[str, asyncio.AbstractEventLoop] = {}
        self._dispatch_loop_holder: dict[str, asyncio.AbstractEventLoop] = {}
        self._telegram: TelegramChannel | None = None
        self._telegram_thread: threading.Thread | None = None
        self._proactive_thread: threading.Thread | None = None
        self._dispatch_thread: threading.Thread | None = None
        self._http: HTTPChannel | None = None

        self._proactive_runtime: ProactiveLoop | None = None
        self._background_runtime: BackgroundRuntime | None = None
        self._subagent_runtime = None
        self._message_bus: MessageBus | None = None
        self._event_bus: EventBus | None = None
        self._chat_worker: ChatWorker | None = None
        self._memory_runtime = None
        self._memory_optimizer_loop: MemoryOptimizerLoop | None = None
        self._mcp_registry: McpServerRegistry | None = None
        self._plugin_manager = None

    @property
    def state(self) -> str:
        """返回当前生命周期状态。"""

        with self._lifecycle_lock:
            return self._state

    def init(self) -> None:
        """获取进程锁并创建全部运行时资源，但不启动后台线程。"""

        with self._lifecycle_lock:
            if self._state != "new":
                raise RuntimeError(f"应用不能从状态 {self._state} 初始化")
            try:
                self._lock.acquire()
                self._lock_owned = True
                self._initialize_runtime()
                self._state = "initialized"
            except WorkspaceAlreadyRunningError:
                self._release_lock()
                raise
            except Exception:
                self._release_lock()
                raise

    def start(self) -> None:
        """启动所有后台服务并立即返回。"""

        with self._lifecycle_lock:
            if self._state != "initialized":
                raise RuntimeError(f"应用不能从状态 {self._state} 启动")
            self._stop_event.clear()
            self._state = "starting"

        try:
            self._start_telegram()
            if self._http is not None and self.config.channels.http_enabled:
                self._http.start()
                logger.info("HTTP channel started")

            if self._chat_worker is not None:
                self._chat_worker.start_background()
            if self._background_runtime is not None:
                self._background_runtime.start()
            print("scheduler started")

            if self._memory_optimizer_loop is not None:
                self._memory_optimizer_loop.start()
                print("memory optimizer started")

            self._start_proactive()

            # 等待 Telegram 完成订阅后再启动出站分发，避免首批消息丢失。
            time.sleep(1.0)
            self._start_dispatch()

            with self._lifecycle_lock:
                self._state = "running"
            print("All services started. Press Ctrl+C to stop.")
        except Exception:
            logger.exception("服务启动失败，开始清理已启动资源")
            self.stop()
            raise

    def wait(self) -> None:
        """阻塞当前线程，直到应用收到停止信号。"""

        self._stop_event.wait()

    def stop(self) -> None:
        """按逆序停止服务、等待线程退出并释放进程锁。"""

        with self._lifecycle_lock:
            if self._state == "stopped":
                return
            if self._state == "new":
                self._state = "stopped"
                return
            self._state = "stopping"
            self._stop_event.set()

        try:
            # 先停止入口，阻止新的入站消息继续进入业务线程。
            self._stop_telegram()
            if self._http is not None and self.config.channels.http_enabled:
                self._http.stop()

            if self._proactive_runtime is not None:
                self._proactive_runtime.request_stop()
            if self._memory_optimizer_loop is not None:
                self._memory_optimizer_loop.stop()
            if self._chat_worker is not None:
                self._chat_worker.stop_background()
            if self._background_runtime is not None:
                self._background_runtime.stop()
            if self._subagent_runtime is not None:
                self._subagent_runtime.manager.shutdown()

            if self._plugin_manager is not None:
                asyncio.run(self._plugin_manager.shutdown_all())
            if self._mcp_registry is not None:
                self._mcp_registry.stop_all()
            self._shutdown_memory_events()
            self._stop_dispatch()
            self._join_threads()
        except Exception:
            logger.exception("服务停止过程中出现异常")
        finally:
            self._release_lock()
            with self._lifecycle_lock:
                self._state = "stopped"
            print("Shutdown complete.")

    def _initialize_runtime(self) -> None:
        from infra.telemetry import configure_logging

        cfg = self.config
        configure_logging(cfg.logging.level, WORKSPACE_LAYOUT.app_log_file)
        print(
            "Config summary: "
            f"http_enabled={cfg.channels.http_enabled}, "
            f"jobs_queue={cfg.jobs.max_async_queue}, "
            f"subagent_max={cfg.subagent.max_concurrency}"
        )

        (
            self._proactive_runtime,
            self._background_runtime,
            self._subagent_runtime,
            _runtime_service,
            self._message_bus,
            self._event_bus,
            self._chat_worker,
            _pipeline,
            tool_registry,
            self._memory_runtime,
            self._memory_optimizer_loop,
            self._mcp_registry,
            self._plugin_manager,
        ) = create_app_runtime(cfg)

        self._http = HTTPChannel(
            host=cfg.channels.http_host,
            port=cfg.channels.http_port,
            message_bus=self._message_bus,
        )

        if cfg.channels.telegram_bot_token:
            allowed_users = {
                user.strip()
                for user in cfg.channels.telegram_allowed_users.split(",")
                if user.strip()
            }
            allowed_groups = {
                int(group.strip())
                for group in cfg.channels.telegram_allowed_groups.split(",")
                if group.strip().isdigit()
            }
            self._telegram = TelegramChannel(
                bot_token=cfg.channels.telegram_bot_token,
                allowed_users=list(allowed_users),
                allowed_groups=list(allowed_groups),
            )
            message_push = MessagePushTool()
            message_push.register_channel(
                "telegram",
                send=self._telegram.send,
                send_file=self._telegram.send_file,
                send_image=self._telegram.send_image,
            )
            tool_registry.register(message_push)

        self._channel_context = ChannelContext(
            bus=self._message_bus,
            event_bus=self._event_bus,
            log=logger,
        )
        print("Flow Agent (MessageBus 架构)")
        print("Services starting...")

    def _start_telegram(self) -> None:
        if not (self.config.channels.telegram_enabled and self._telegram is not None):
            return

        def run_telegram() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._telegram_loop_holder["loop"] = loop
            try:
                loop.run_until_complete(self._telegram.start(self._channel_context))
            finally:
                self._telegram_loop_holder.pop("loop", None)
                loop.close()

        self._telegram_thread = threading.Thread(
            target=run_telegram,
            name="telegram-channel",
            daemon=True,
        )
        self._telegram_thread.start()
        self._threads.append(self._telegram_thread)
        print("telegram channel started")

    def _start_proactive(self) -> None:
        if self._proactive_runtime is None:
            return

        def run_proactive() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._proactive_runtime.run())
            finally:
                loop.close()

        self._proactive_thread = threading.Thread(
            target=run_proactive,
            name="proactive-loop",
            daemon=True,
        )
        self._proactive_thread.start()
        self._threads.append(self._proactive_thread)
        print("proactive loop started")

    def _start_dispatch(self) -> None:
        if self._message_bus is None:
            return

        def run_dispatch() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._dispatch_loop_holder["loop"] = loop
            try:
                loop.run_until_complete(self._message_bus.start_dispatch_task())
            finally:
                self._dispatch_loop_holder.pop("loop", None)
                loop.close()

        self._dispatch_thread = threading.Thread(
            target=run_dispatch,
            name="message-dispatch",
            daemon=True,
        )
        self._dispatch_thread.start()
        self._threads.append(self._dispatch_thread)
        print("MessageBus dispatch task started")

    def _stop_telegram(self) -> None:
        telegram = self._telegram
        loop = self._telegram_loop_holder.get("loop")
        if telegram is None or loop is None or loop.is_closed():
            return
        future = asyncio.run_coroutine_threadsafe(telegram.stop(), loop)
        try:
            future.result(timeout=5.0)
        except Exception:
            logger.exception("Telegram 渠道停止失败")

    def _stop_dispatch(self) -> None:
        message_bus = self._message_bus
        loop = self._dispatch_loop_holder.get("loop")
        if message_bus is None or loop is None or loop.is_closed():
            return
        future = asyncio.run_coroutine_threadsafe(
            message_bus.stop_dispatch_task(),
            loop,
        )
        try:
            future.result(timeout=5.0)
        except Exception:
            logger.exception("MessageBus 分发任务停止失败")

    def _shutdown_memory_events(self) -> None:
        runtime = self._memory_runtime
        executor = getattr(runtime, "event_executor", None)
        if executor is None:
            return
        try:
            executor.shutdown(wait=True, cancel_futures=True)
        except TypeError:
            executor.shutdown(wait=True)
        runtime.event_executor = None

    def _join_threads(self) -> None:
        current = threading.current_thread()
        for thread in self._threads:
            if thread is current:
                continue
            thread.join(timeout=8.0)
            if thread.is_alive():
                logger.warning("服务线程停止超时: %s", thread.name)
        self._threads.clear()

    def _release_lock(self) -> None:
        if not self._lock_owned:
            return
        self._lock.release()
        self._lock_owned = False

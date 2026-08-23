"""Flow Agent 应用生命周期。"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

from application.capabilities.tools.message_push import MessagePushTool
from application.capabilities.app.capability_query import CapabilityQueryService
from application.capabilities.skills.installer import SkillInstaller
from application.capabilities.mcp.server_registry import McpServerRegistry
from application.capabilities.plugins.plugin_loader import PluginManager
from application.delegation.app.runtime import SubagentRuntime
from application.memory.app.memory_runtime import MemoryRuntime
from application.passive.app.passive_loop import PassiveLoop
from application.passive.app.session_query import SessionQueryService
from application.schedule.app.runtime import SchedulerService
from application.memory.app.optimizer import MemoryOptimizerLoop
from application.proactive.app.loop import ProactiveLoop
from application.automation.app.runtime import AutomationRuntime
from bootstrap.container import create_app_runtime
from infra.config import AppConfig
from infra.workspace import WORKSPACE_LAYOUT
from infra.workspace import (
    WorkspaceAlreadyRunningError,
    WorkspaceProcessLock,
)
from infra.bus.event import EventBus
from infra.bus.message import MessageBus
from application.agent.app.tracing import TraceTimeline
from interfaces.admin.router import create_admin_app
from interfaces.admin.server import AdminServer
from interfaces.channels.base import ChannelContext
from interfaces.channels.service import ChannelService, register_builtin_channels

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
        self._dispatch_loop_holder: dict[str, asyncio.AbstractEventLoop] = {}
        self._dispatch_ready = threading.Event()
        self._proactive_thread: threading.Thread | None = None
        self._dispatch_thread: threading.Thread | None = None
        self._channel_service = ChannelService()

        self._proactive_runtime: ProactiveLoop | None = None
        self._automation_runtime: AutomationRuntime | None = None
        self._subagent_runtime: SubagentRuntime | None = None
        self._message_bus: MessageBus | None = None
        self._event_bus: EventBus | None = None
        self._passive_loop: PassiveLoop | None = None
        self._memory_runtime: MemoryRuntime | None = None
        self._memory_optimizer_loop: MemoryOptimizerLoop | None = None
        self._mcp_registry: McpServerRegistry | None = None
        self._plugin_manager: PluginManager | None = None
        self._admin_timeline: TraceTimeline | None = None
        self._session_query: SessionQueryService | None = None
        self._scheduler: SchedulerService | None = None
        self._capability_query: CapabilityQueryService | None = None
        self._skill_installer = SkillInstaller(WORKSPACE_LAYOUT.installed_skills_dir)
        self._admin_server: AdminServer | None = None

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
            self._channel_service.start_all()
            for adapter in self._channel_service.adapters():
                print(f"{adapter.name} channel started")
            if self._admin_server is not None:
                self._admin_server.start()

            if self._passive_loop is not None:
                self._passive_loop.start_background()
            if self._automation_runtime is not None:
                self._automation_runtime.start()
            print("scheduler started")

            if self._memory_optimizer_loop is not None:
                self._memory_optimizer_loop.start()
                print("memory optimizer started")

            self._start_proactive()

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

        failures: list[tuple[str, BaseException]] = []

        def attempt(name: str, action) -> None:
            try:
                action()
            except (Exception, KeyboardInterrupt) as exc:
                failures.append((name, exc))
                logger.exception("服务停止失败: component=%s", name)

        # 先停止入口，阻止新的入站消息继续进入业务线程；单个渠道失败时继续清理。
        attempt("channels.stop", self._channel_service.stop_all)
        admin_server = getattr(self, "_admin_server", None)
        if admin_server is not None:
            attempt("admin_api.stop", admin_server.stop)
            attempt("admin_api.join", lambda: admin_server.join(timeout=8.0))
        if self._proactive_runtime is not None:
            attempt("proactive", self._proactive_runtime.request_stop)
        if self._memory_optimizer_loop is not None:
            attempt("memory_optimizer", self._memory_optimizer_loop.stop)
        if self._passive_loop is not None:
            attempt("passive", self._passive_loop.stop_background)
        if self._automation_runtime is not None:
            attempt("automation", self._automation_runtime.stop)
        if self._subagent_runtime is not None:
            attempt("subagent", self._subagent_runtime.manager.shutdown)

        if self._plugin_manager is not None:
            plugin_manager = self._plugin_manager
            attempt(
                "plugins",
                lambda: asyncio.run(plugin_manager.shutdown_all()),
            )
        if self._mcp_registry is not None:
            attempt("mcp", self._mcp_registry.stop_all)
        attempt("memory_events", self._shutdown_memory_events)
        attempt("message_dispatch", self._stop_dispatch)
        attempt("channels.join", lambda: self._channel_service.join_all(timeout=8.0))
        attempt("service_threads", self._join_threads)
        if failures:
            logger.error(
                "服务停止完成，但有 %d 个组件报告异常: %s",
                len(failures),
                ", ".join(name for name, _ in failures),
            )
        self._release_lock()
        with self._lifecycle_lock:
            self._state = "stopped"
        print("Shutdown complete.")

    def _initialize_runtime(self) -> None:
        from infra.telemetry import configure_logging

        cfg = self.config
        configure_logging(cfg.logging.level, WORKSPACE_LAYOUT.app_log_file)
        enabled_channels = {
            name
            for name, options in cfg.channels.adapters.items()
            if bool(options.get("enabled", False))
        }
        print(
            "Config summary: "
            f"channels={','.join(sorted(enabled_channels)) or 'none'}, "
            f"jobs_queue={cfg.jobs.max_async_queue}, "
            f"subagent_max={cfg.subagent.max_concurrency}"
        )

        (
            self._proactive_runtime,
            self._automation_runtime,
            self._subagent_runtime,
            _runtime_service,
            self._message_bus,
            self._event_bus,
            self._passive_loop,
            _pipeline,
            tool_registry,
            self._memory_runtime,
            self._memory_optimizer_loop,
            self._mcp_registry,
            self._plugin_manager,
            self._session_query,
            self._scheduler,
            self._capability_query,
        ) = create_app_runtime(cfg)
        if cfg.admin_api.enabled:
            if (
                self._session_query is None
                or self._scheduler is None
                or self._capability_query is None
            ):
                raise RuntimeError("管理查询服务未初始化")
            self._admin_timeline = TraceTimeline()
            self._event_bus.subscribe(self._admin_timeline)
            self._admin_server = AdminServer(
                create_admin_app(
                    self._admin_timeline,
                    self._session_query,
                    self._scheduler,
                    self._capability_query,
                    self._skill_installer,
                    self._mcp_registry,
                ),
                host=cfg.admin_api.host,
                port=cfg.admin_api.port,
            )
        self._channel_context = ChannelContext(
            bus=self._message_bus,
            event_bus=self._event_bus,
            log=logger,
            attachment_dir=WORKSPACE_LAYOUT.inbound_attachments_dir,
        )
        register_builtin_channels(self._channel_service)
        self._channel_service.build_enabled(cfg.channels, self._channel_context)
        message_push = MessagePushTool()
        for adapter in self._channel_service.adapters():
            message_push.register_adapter(adapter)
        if self._channel_service.adapters():
            tool_registry.register(message_push)
        print("Flow Agent (MessageBus 架构)")
        print("Services starting...")

    def _start_proactive(self) -> None:
        proactive_runtime = self._proactive_runtime
        if proactive_runtime is None:
            return

        def run_proactive() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(proactive_runtime.run())
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
        message_bus = self._message_bus
        if message_bus is None:
            return
        self._dispatch_ready.clear()

        def run_dispatch() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._dispatch_loop_holder["loop"] = loop
            self._dispatch_ready.set()
            try:
                loop.run_until_complete(message_bus.start_dispatch_task())
            finally:
                self._dispatch_loop_holder.pop("loop", None)
                self._dispatch_ready.clear()
                loop.close()

        self._dispatch_thread = threading.Thread(
            target=run_dispatch,
            name="message-dispatch",
            daemon=True,
        )
        self._dispatch_thread.start()
        self._threads.append(self._dispatch_thread)
        print("MessageBus dispatch task started")

    def _stop_dispatch(self) -> None:
        message_bus = self._message_bus
        loop = self._dispatch_loop_holder.get("loop")
        if loop is None:
            ready = getattr(self, "_dispatch_ready", None)
            thread = getattr(self, "_dispatch_thread", None)
            if ready is not None and (thread is None or thread.is_alive()):
                ready.wait(timeout=5.0)
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
        if runtime is None or runtime.event_executor is None:
            return
        executor = runtime.event_executor
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

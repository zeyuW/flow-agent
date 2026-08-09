"""基于霍克斯过程强度调度主动检查循环。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Protocol

from application.proactive.domain.models import AgentTick
from application.proactive.domain.hawkes import (
    HawkesConfig,
    HawkesProcessModel,
)
from application.proactive.app.lifecycle import (
    ProactiveLifecycle,
    compile_proactive_lifecycle,
)
from application.proactive.app.mcp_polling import McpPollingModule

logger = logging.getLogger(__name__)


class _PipelineProtocol(Protocol):
    async def run(
        self,
        *,
        chat_id: str,
        base_score: float,
        is_busy: bool,
    ) -> AgentTick: ...


class _PoolProtocol(Protocol):
    async def connect_all(self) -> None: ...

    async def close_all(self) -> None: ...


class ProactiveLoop:
    """主动检查循环，负责资源生命周期、调度唤醒和五阶段管线执行。"""

    _EVENT_WEIGHTS = {
        "user_message": 1.0,
        "reaction": 0.6,
        "follow_up": 0.8,
    }

    def __init__(
        self,
        pipeline: _PipelineProtocol,
        mcp_pool: _PoolProtocol,
        *,
        chat_id: str = "",
        min_interval: float = 60.0,
        max_interval: float = 1800.0,
        is_busy_fn: Callable[[], bool] | None = None,
        hawkes_config: HawkesConfig | None = None,
        hawkes_enabled: bool = True,
        polling_module=None,
        state_store=None,
        trace_recorder=None,
    ) -> None:
        self._pipeline = pipeline
        self._pool = mcp_pool
        self._chat_id = chat_id
        self._min_interval = min_interval
        self._max_interval = max_interval
        self._is_busy_fn = is_busy_fn
        self._hawkes_enabled = hawkes_enabled
        self._running = False
        self._is_executing = False
        self._task: asyncio.Task | None = None
        self._polling_module = polling_module
        self._state_store = state_store
        self._trace_recorder = trace_recorder
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._wake_event: asyncio.Event | None = None
        self._last_started_at: datetime | None = None
        self._last_finished_at: datetime | None = None
        self._last_interval: float | None = None
        self._last_tick = None
        self._event_bridge: object | None = None
        self._refresh_lock: asyncio.Lock | None = None
        self._refresh_task: asyncio.Task | None = None
        self._pending_contributions: tuple[list, list[object]] | None = None

        config = hawkes_config or HawkesConfig(
            min_interval=min_interval,
            max_interval=max_interval,
        )
        self._hawkes = HawkesProcessModel(config, state_store=state_store)

    async def run(self) -> None:
        """启动资源并持续运行主动检查，直到收到停止信号。"""

        if self._running:
            return
        self._running = True
        self._event_loop = asyncio.get_running_loop()
        self._wake_event = asyncio.Event()
        self._refresh_lock = asyncio.Lock()
        logger.info("主动链路已启动: target=%s", self._chat_id)

        try:
            await self._connect_resources()
            pending = self._pending_contributions
            self._pending_contributions = None
            if pending is not None:
                await self.reconcile_contributions(*pending)
            await self._run_loop()
        finally:
            self._running = False
            self._is_executing = False
            await self._close_resources()
            self._event_loop = None
            self._wake_event = None
            self._refresh_lock = None
            logger.info("主动链路已停止: target=%s", self._chat_id)

    async def _connect_resources(self) -> None:
        """连接主动链路拥有的外部资源。"""

        try:
            await self._pool.connect_all()
        except Exception:
            logger.exception("MCP 连接池连接失败")

        if self._polling_module is not None:
            try:
                await self._polling_module.start()
            except Exception:
                logger.exception("MCP 轮询模块启动失败")
        start_extensions = getattr(self._pipeline, "start_extensions", None)
        if callable(start_extensions):
            await start_extensions()

    async def _close_resources(self) -> None:
        """逆序关闭主动链路拥有的外部资源。"""

        stop_extensions = getattr(self._pipeline, "stop_extensions", None)
        if callable(stop_extensions):
            try:
                await stop_extensions()
            except Exception:
                logger.exception("主动扩展模块停止失败")
        if self._polling_module is not None:
            try:
                await self._polling_module.stop()
            except Exception:
                logger.exception("MCP 轮询模块停止失败")
        try:
            await self._pool.close_all()
        except Exception:
            logger.exception("MCP 连接池关闭失败")
        if hasattr(self._pipeline, "close"):
            try:
                self._pipeline.close()
            except Exception:
                logger.exception("主动链路状态存储关闭失败")

    async def _run_loop(self) -> None:
        """启动后等待一个调度间隔，再按霍克斯强度或固定间隔检查。"""

        next_interval = self._compute_next_interval()
        self._last_interval = next_interval
        logger.info(
            "主动链路启动后首次检查: interval=%.2fs",
            next_interval,
        )
        while self._running:
            if next_interval > 0:
                due = await self._wait_until_due(next_interval)
                if not due:
                    return
            if not self._running:
                return
            await self._run_single_tick()
            next_interval = self._compute_next_interval()
            self._last_interval = next_interval
            logger.info(
                "主动链路下次检查: interval=%.2fs intensity=%.4f events_1h=%d",
                next_interval,
                self.get_current_intensity(),
                self._hawkes.get_event_count(3600.0),
            )

    async def _wait_until_due(self, interval: float) -> bool:
        """等待截止时间；新互动只允许把已有截止时间提前。"""

        loop = asyncio.get_running_loop()
        deadline = loop.time() + interval
        while self._running:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return True
            wake_event = self._wake_event
            if wake_event is None:
                await asyncio.sleep(remaining)
                return self._running
            try:
                await asyncio.wait_for(wake_event.wait(), timeout=remaining)
            except asyncio.TimeoutError:
                return self._running
            wake_event.clear()
            if not self._running:
                return False
            refreshed_deadline = loop.time() + self._compute_next_interval()
            deadline = min(deadline, refreshed_deadline)
        return False

    async def _run_single_tick(self) -> None:
        lock = self._refresh_lock
        if lock is None:
            await self._run_single_tick_unlocked()
            return
        async with lock:
            await self._run_single_tick_unlocked()

    async def _run_single_tick_unlocked(self) -> None:
        """隔离单轮异常，避免一次失败终止整个主动循环。"""

        self._is_executing = True
        self._last_started_at = datetime.now(timezone.utc)
        try:
            is_busy = self._is_busy_fn() if self._is_busy_fn else False
            base_score = self.get_current_intensity()
            self._last_tick = await self._pipeline.run(
                chat_id=self._chat_id,
                base_score=base_score,
                is_busy=is_busy,
            )
            gate = self._last_tick.gate_result
            logger.info(
                "主动链路检查完成: gate=%s reason=%s sent=%s",
                bool(gate and gate.passed),
                gate.reason if gate is not None else "no_gate",
                bool(
                    self._last_tick.deliver_result
                    and self._last_tick.deliver_result.sent
                ),
            )
            if self._trace_recorder is not None:
                self._trace_recorder.record(self.status_snapshot())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("主动链路单次检查失败")
        finally:
            self._last_finished_at = datetime.now(timezone.utc)
            self._is_executing = False

    async def reconcile_contributions(
        self,
        sources: list,
        modules: list[object],
    ) -> None:
        """在主动事件循环中准备并原子替换插件贡献。"""

        candidate_lifecycle = compile_proactive_lifecycle(
            modules,
            initial_slots=("proactive:tick",),
        )
        candidate_polling = (
            McpPollingModule(self._pool, list(sources)) if sources else None
        )
        lock = self._refresh_lock
        if lock is None:
            lock = asyncio.Lock()
            self._refresh_lock = lock
        async with lock:
            if self._running and candidate_polling is not None:
                try:
                    await candidate_polling.start()
                except BaseException:
                    await candidate_polling.stop()
                    raise

            old_polling = self._polling_module
            old_lifecycle = getattr(self._pipeline, "_lifecycle", None)
            if old_lifecycle is not None and self._running:
                await old_lifecycle.stop()
            if old_polling is not None:
                await old_polling.stop()
            replace = getattr(self._pipeline, "replace_contributions", None)
            if not callable(replace):
                raise RuntimeError("主动管道不支持插件贡献刷新")
            replace(list(sources), candidate_lifecycle)
            self._polling_module = candidate_polling

    def request_contributions_refresh(
        self, sources: list, modules: list[object]
    ) -> None:
        """从插件 watcher 线程安全地请求主动贡献刷新。"""

        loop = self._event_loop
        if loop is None or loop.is_closed():
            self._pending_contributions = (list(sources), list(modules))
            return
        if not self._running:
            self._pending_contributions = (list(sources), list(modules))
            return
        if self._refresh_task is not None and not self._refresh_task.done():
            return

        def schedule() -> None:
            self._refresh_task = asyncio.create_task(
                self.reconcile_contributions(list(sources), list(modules)),
                name="proactive_contribution_reconcile",
            )

        loop.call_soon_threadsafe(schedule)

    def _compute_next_interval(self) -> float:
        """根据配置选择霍克斯调度或保守固定调度。"""

        if not self._hawkes_enabled:
            return self._max_interval
        return self._hawkes.compute_next_interval()

    def request_stop(self) -> None:
        """同步发出停止信号，供跨线程运行时管理器调用。"""

        self._running = False
        self._notify_schedule_changed()

    def apply_runtime_config(
        self,
        *,
        min_interval: float,
        max_interval: float,
        max_per_day: int,
        cooldown: float,
        base_intensity: float,
        excitation_alpha: float,
        decay_beta: float,
        time_constant: float,
        drift_min_interval_hours: float | None = None,
    ) -> None:
        """热更新不要求重建外部连接的主动调度参数。"""

        candidate = HawkesConfig(
            base_intensity=base_intensity,
            excitation_alpha=excitation_alpha,
            decay_beta=decay_beta,
            time_constant=time_constant,
            min_interval=min_interval,
            max_interval=max_interval,
        )
        self._min_interval = candidate.min_interval
        self._max_interval = candidate.max_interval
        self._hawkes._config = candidate
        self._pipeline._cooldown = max(0.0, float(cooldown))
        self._pipeline._any_action.max_per_day = max(1, int(max_per_day))
        self._pipeline._any_action.min_interval = max(0.0, float(cooldown))
        if drift_min_interval_hours is not None:
            self._pipeline._drift_min_interval = (
                max(0.0, float(drift_min_interval_hours)) * 3600.0
            )
        self._notify_schedule_changed()

    async def stop(self) -> None:
        """停止循环，并在同一事件循环中等待资源清理完成。"""

        self.request_stop()
        task = self._task
        if task is None:
            if not self._running:
                await self._close_resources()
            return
        if task.done() or task is asyncio.current_task():
            return
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if task.get_loop() is current_loop:
            await task

    async def start_background(self) -> asyncio.Task:
        """在当前事件循环中创建唯一的后台主动任务。"""

        if self._task is not None and not self._task.done():
            return self._task
        self._task = asyncio.create_task(self.run(), name="proactive_loop")
        return self._task

    def record_user_interaction(
        self,
        event_type: str = "user_message",
        *,
        timestamp: float | None = None,
        weight: float | None = None,
    ) -> None:
        """记录用户互动并唤醒调度器重新评估截止时间。"""

        effective_weight = (
            self._EVENT_WEIGHTS.get(event_type, 1.0) if weight is None else weight
        )
        self._hawkes.add_interaction(
            event_type,
            timestamp=timestamp,
            weight=effective_weight,
        )
        if self._state_store is not None and event_type == "user_message":
            self._state_store.record_user_interaction(
                self._chat_id,
                timestamp=timestamp,
            )
        self._notify_schedule_changed()

    def _notify_schedule_changed(self) -> None:
        """以线程安全方式唤醒主动循环。"""

        loop = self._event_loop
        wake_event = self._wake_event
        if loop is None or wake_event is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(wake_event.set)

    def get_current_intensity(self) -> float:
        """返回监控使用的当前强度。"""

        if not self._hawkes_enabled:
            return 0.0
        return self._hawkes.get_current_intensity()

    def get_next_interval(self) -> float:
        """返回按当前状态估算的下一次检查间隔。"""

        return self._compute_next_interval()

    def status_snapshot(self) -> dict[str, object]:
        """返回运行时服务可直接消费的主动链路状态。"""

        tick = self._last_tick
        gate = tick.gate_result if tick is not None else None
        deliver = tick.deliver_result if tick is not None else None
        return {
            "event": "proactive_tick",
            "gate_reason": gate.reason if gate is not None else None,
            "phase_trace": list(tick.phase_trace) if tick is not None else [],
            "sent": bool(deliver and deliver.sent),
            "running": self._running,
            "is_executing": self._is_executing,
            "last_started_at": (
                self._last_started_at.isoformat()
                if self._last_started_at is not None
                else None
            ),
            "last_finished_at": (
                self._last_finished_at.isoformat()
                if self._last_finished_at is not None
                else None
            ),
            "last_interval": self._last_interval,
            "hawkes_enabled": self._hawkes_enabled,
            "current_intensity": self.get_current_intensity(),
            "events_1h": self._hawkes.get_event_count(3600.0),
        }

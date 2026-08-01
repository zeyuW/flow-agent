"""基于霍克斯过程强度调度主动检查循环。"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from flow_agent.proactive.models import AgentTick
from flow_agent.proactive.lifecycle import ProactiveLifecycle, compile_proactive_lifecycle
from flow_agent.proactive.mcp_polling import McpPollingModule

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


@dataclass(slots=True)
class HawkesConfig:
    """霍克斯过程及主动检查间隔配置。"""

    base_intensity: float = 0.1
    excitation_alpha: float = 0.5
    decay_beta: float = 0.1
    time_constant: float = 60.0
    min_interval: float = 60.0
    max_interval: float = 1800.0
    event_retention_seconds: float = 86400.0
    daytime_start_hour: int = 8
    nighttime_start_hour: int = 22
    daytime_multiplier: float = 1.5
    nighttime_multiplier: float = 0.5

    def __post_init__(self) -> None:
        """尽早拒绝会导致无效强度或间隔的配置。"""

        if self.base_intensity < 0:
            raise ValueError("base_intensity 不能小于 0")
        if self.excitation_alpha < 0:
            raise ValueError("excitation_alpha 不能小于 0")
        if self.decay_beta < 0:
            raise ValueError("decay_beta 不能小于 0")
        if self.time_constant <= 0:
            raise ValueError("time_constant 必须大于 0")
        if self.min_interval <= 0:
            raise ValueError("min_interval 必须大于 0")
        if self.max_interval < self.min_interval:
            raise ValueError("max_interval 不能小于 min_interval")
        if self.event_retention_seconds <= 0:
            raise ValueError("event_retention_seconds 必须大于 0")


@dataclass(slots=True)
class InteractionEvent:
    """会影响主动检查强度的真实互动事件。"""

    timestamp: float
    event_type: str = "user_message"
    weight: float = 1.0


class HawkesProcessModel:
    """根据真实互动事件计算自激强度和下一次检查间隔。

    强度公式为：
    λ(t) = μ(t) + Σ α × weight × exp(-β × Δt_minutes)

    这里只用霍克斯强度驱动调度，不把主动检查或主动发送本身重新记为
    自激事件，避免系统在没有新用户互动时形成发送风暴。
    """

    def __init__(
        self,
        config: HawkesConfig,
        *,
        clock: Callable[[], float] = time.time,
        local_hour_fn: Callable[[float], int] | None = None,
        state_store=None,
    ) -> None:
        self._config = config
        self._clock = clock
        self._local_hour_fn = local_hour_fn or self._local_hour
        self._events: list[InteractionEvent] = []
        self._last_tick_time: float = 0.0
        self._lock = threading.RLock()
        self._state_store = state_store
        if state_store is not None:
            cutoff = self._clock() - self._config.event_retention_seconds
            for ts, kind, weight in state_store.load_interaction_events(cutoff):
                self._events.append(
                    InteractionEvent(timestamp=ts, event_type=kind, weight=weight)
                )


    @staticmethod
    def _local_hour(timestamp: float) -> int:
        """按运行机器的本地时区获取小时。"""

        return datetime.fromtimestamp(timestamp).hour

    def add_interaction(
        self,
        event_type: str = "user_message",
        *,
        timestamp: float | None = None,
        weight: float = 1.0,
    ) -> None:
        """记录一条真实互动并清理超出保留窗口的旧事件。"""

        if weight <= 0:
            return
        occurred_at = self._clock() if timestamp is None else float(timestamp)
        with self._lock:
            self._events.append(
                InteractionEvent(
                    timestamp=occurred_at,
                    event_type=event_type,
                    weight=float(weight),
                )
            )
            self._cleanup_old_events_locked(occurred_at)
        if self._state_store is not None:
            self._state_store.append_interaction_event(
                occurred_at, event_type, float(weight)
            )
        logger.debug(
            "记录霍克斯互动事件: type=%s weight=%.3f timestamp=%.3f",
            event_type,
            weight,
            occurred_at,
        )

    def _cleanup_old_events_locked(self, current_time: float) -> None:
        """调用方持锁时移除超出保留窗口的事件。"""

        cutoff = current_time - self._config.event_retention_seconds
        self._events = [event for event in self._events if event.timestamp >= cutoff]

    def _compute_base_intensity(self, current_time: float) -> float:
        """根据本地昼夜时段计算基础强度 μ(t)。"""

        hour = self._local_hour_fn(current_time)
        is_daytime = (
            self._config.daytime_start_hour <= hour < self._config.nighttime_start_hour
        )
        multiplier = (
            self._config.daytime_multiplier
            if is_daytime
            else self._config.nighttime_multiplier
        )
        return self._config.base_intensity * multiplier

    def _compute_intensity(self, current_time: float) -> float:
        """计算指定时刻的霍克斯强度。"""

        with self._lock:
            self._cleanup_old_events_locked(current_time)
            events = tuple(self._events)

        excitation_sum = 0.0
        for event in events:
            elapsed_seconds = current_time - event.timestamp
            if elapsed_seconds < 0:
                continue
            elapsed_minutes = elapsed_seconds / 60.0
            excitation_sum += (
                self._config.excitation_alpha
                * event.weight
                * math.exp(-self._config.decay_beta * elapsed_minutes)
            )
        return max(0.0, self._compute_base_intensity(current_time) + excitation_sum)

    def compute_next_interval(self, current_time: float | None = None) -> float:
        """把当前强度映射为受上下限约束的下一次检查间隔。"""

        now = self._clock() if current_time is None else float(current_time)
        intensity = self._compute_intensity(now)
        if intensity <= 1e-12:
            interval = self._config.max_interval
        else:
            interval = self._config.time_constant / intensity
        interval = max(
            self._config.min_interval,
            min(self._config.max_interval, interval),
        )
        with self._lock:
            self._last_tick_time = now
        return interval

    def get_current_intensity(self, current_time: float | None = None) -> float:
        """返回当前霍克斯强度。"""

        now = self._clock() if current_time is None else float(current_time)
        return self._compute_intensity(now)

    def get_event_count(
        self,
        window_seconds: float = 3600.0,
        *,
        current_time: float | None = None,
    ) -> int:
        """返回指定时间窗口内的互动事件数。"""

        now = self._clock() if current_time is None else float(current_time)
        with self._lock:
            self._cleanup_old_events_locked(now)
            return sum(
                1
                for event in self._events
                if 0 <= now - event.timestamp < window_seconds
            )

    def reset(self) -> None:
        """清空全部互动事件和最近计算时间。"""

        with self._lock:
            self._events.clear()
            self._last_tick_time = 0.0
        logger.info("霍克斯过程模型已重置")


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
        """首次立即检查，后续按霍克斯强度或固定间隔调度。"""

        next_interval = 0.0
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

    def request_contributions_refresh(self, sources: list, modules: list[object]) -> None:
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

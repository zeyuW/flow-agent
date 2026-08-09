"""主动业务的霍克斯强度模型。

本文件只负责根据真实用户互动计算主动检查强度和下一次检查间隔，
不负责异步调度、MCP 资源或主动内容生成。
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

logger = logging.getLogger(__name__)


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

    主动检查和主动发送本身不会重新记为自激事件，避免无用户互动时形成发送风暴。
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
        self._last_tick_time = 0.0
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
        is_daytime = self._config.daytime_start_hour <= hour < self._config.nighttime_start_hour
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
            excitation_sum += self._config.excitation_alpha * event.weight * math.exp(
                -self._config.decay_beta * (elapsed_seconds / 60.0)
            )
        return max(0.0, self._compute_base_intensity(current_time) + excitation_sum)

    def compute_next_interval(self, current_time: float | None = None) -> float:
        """把当前强度映射为受上下限约束的下一次检查间隔。"""

        now = self._clock() if current_time is None else float(current_time)
        intensity = self._compute_intensity(now)
        interval = self._config.max_interval if intensity <= 1e-12 else self._config.time_constant / intensity
        interval = max(self._config.min_interval, min(self._config.max_interval, interval))
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

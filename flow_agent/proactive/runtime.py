import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from flow_agent.proactive.pipeline import ProactiveTickRunner
from flow_agent.proactive.types import SchedulerStatus


logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IntervalScheduler:
    '''在固定间隔内运行主动运行时，没有重入执行'''

    def __init__(self, interval_seconds: int, task: Callable[[], None]) -> None:
        self.interval_seconds = interval_seconds
        self.task = task
        self._running = False
        self._is_executing = False
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_started_at: datetime | None = None
        self._last_finished_at: datetime | None = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_seconds + 1)
            self._thread = None

    def status(self) -> SchedulerStatus:
        return SchedulerStatus(
            running=self._running,
            is_executing=self._is_executing,
            last_started_at=self._last_started_at,
            last_finished_at=self._last_finished_at,
        )

    '''运行一次'''
    def run_once(self) -> None:
        if not self._lock.acquire(blocking=False):
            return
        try:
            self._is_executing = True
            self._last_started_at = _utc_now()
            self.task()
        except Exception:
            logger.exception("proactive scheduler task failed")
        finally:
            self._last_finished_at = _utc_now()
            self._is_executing = False
            self._lock.release()

    def _run_loop(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            self.run_once()


@dataclass(slots=True)
class ProactiveRuntime:
    '''
    调度器 
    执行器
    '''
    scheduler: IntervalScheduler
    tick_runner: ProactiveTickRunner

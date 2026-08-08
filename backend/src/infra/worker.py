"""共享后台 worker 生命周期和线程池基础设施。

本模块同时提供常驻 worker 的停止信号管理和短任务线程池。业务模块只依赖
这里的线程生命周期能力，不把具体任务逻辑放入共享基础设施。
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)

WorkerTarget = Callable[[threading.Event], None]


@dataclass
class _WorkerState:
    target: WorkerTarget
    stop_event: threading.Event | None = None
    thread: threading.Thread | None = None


class WorkerManager:
    """管理带停止信号的后台常驻线程，不介入业务重试策略。"""

    def __init__(self) -> None:
        self._workers: dict[str, _WorkerState] = {}
        self._lock = threading.RLock()

    def register(self, name: str, target: WorkerTarget) -> None:
        """注册一个 worker；同名注册会被拒绝。"""

        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("worker 名称不能为空")
        with self._lock:
            if normalized_name in self._workers:
                raise ValueError(f"worker 已注册: {normalized_name}")
            self._workers[normalized_name] = _WorkerState(target=target)

    def start(self, name: str) -> None:
        """启动指定 worker。"""

        with self._lock:
            state = self._get(name)
            if state.thread is not None and state.thread.is_alive():
                raise ValueError(f"worker 已经运行: {name}")
            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._run,
                args=(name, state, stop_event),
                name=f"infra-worker-{name}",
                daemon=True,
            )
            state.stop_event = stop_event
            state.thread = thread
            thread.start()

    def stop(self, name: str, timeout: float = 5.0) -> None:
        """发送停止信号并等待指定 worker 退出；重复停止不会报错。"""

        with self._lock:
            state = self._get(name)
            stop_event = state.stop_event
            thread = state.thread
        if stop_event is None or thread is None:
            return
        stop_event.set()
        if thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout))
        if thread.is_alive():
            logger.warning("worker 停止超时: %s", name)

    def stop_all(self, timeout: float = 5.0) -> None:
        """停止所有已注册 worker。"""

        with self._lock:
            names = list(self._workers)
        for name in names:
            self.stop(name, timeout=timeout)

    def running(self, name: str) -> bool:
        """返回指定 worker 当前是否仍在运行。"""

        with self._lock:
            state = self._get(name)
            return state.thread is not None and state.thread.is_alive()

    def _get(self, name: str) -> _WorkerState:
        state = self._workers.get(name)
        if state is None:
            raise ValueError(f"未知 worker: {name}")
        return state

    @staticmethod
    def _run(name: str, state: _WorkerState, stop_event: threading.Event) -> None:
        try:
            state.target(stop_event)
        except BaseException:
            logger.exception("worker 执行异常: %s", name)


class WorkerPool:
    """封装线程池生命周期，供后台任务和基础设施消费者复用。"""

    def __init__(
        self,
        max_workers: int = 4,
        *,
        thread_name_prefix: str = "infra-worker",
    ) -> None:
        if max_workers <= 0:
            raise ValueError("max_workers 必须大于 0")
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=thread_name_prefix,
        )
        self._shutdown = False

    def submit(
        self,
        function: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Future[Any]:
        """提交一个可调用对象，并返回标准 Future。"""

        if self._shutdown:
            raise RuntimeError("工作池已经关闭")
        return self._executor.submit(function, *args, **kwargs)

    def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
        """停止接收新任务，并按参数等待或取消排队任务。"""

        if self._shutdown:
            return
        self._shutdown = True
        self._executor.shutdown(wait=wait, cancel_futures=cancel_futures)

    def __enter__(self) -> "WorkerPool":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.shutdown()

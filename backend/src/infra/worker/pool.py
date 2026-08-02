"""通用后台工作池。

工作池只提供线程调度能力；任务的业务语义、重试和持久化状态由
``modules/jobs`` 等业务模块负责，避免基础设施反向依赖业务。
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable


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

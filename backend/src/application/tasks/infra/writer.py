"""后台运行记录的串行写入适配器。"""

from __future__ import annotations

import threading
from typing import Any, Callable

from infra.worker.pool import WorkerPool


class JobStoreWriter:
    """使用单线程工作池串行化多个执行线程的存储操作。"""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._pool = WorkerPool(
            max_workers=1,
            thread_name_prefix="background-store-writer",
        )
        self._state_lock = threading.Lock()
        self._closed = False

    def call(self, action: Callable[[], Any]) -> Any:
        """提交一次存储操作并等待其完成，保持调用方状态顺序。"""

        with self._state_lock:
            if self._closed:
                raise RuntimeError("后台存储写入器已经关闭")
        return self._pool.submit(action).result()

    def close(self) -> None:
        """等待排队写入完成，停止工作池并关闭底层存储。"""

        with self._state_lock:
            if self._closed:
                return
            self._closed = True
        self._pool.shutdown(wait=True)
        if hasattr(self._store, "close"):
            self._store.close()

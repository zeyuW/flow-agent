"""后台运行记录的单写入线程。"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class _Request:
    action: Callable[[], Any]
    done: threading.Event
    result: Any = None
    error: BaseException | None = None


class JobStoreWriter:
    """把多个执行线程的存储操作串行化到唯一写入线程。"""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._queue: queue.Queue[_Request | None] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="background-store-writer", daemon=True)
        self._thread.start()

    def call(self, action: Callable[[], Any]) -> Any:
        """提交一次存储操作并等待其完成，保持调用方状态顺序。"""

        request = _Request(action=action, done=threading.Event())
        self._queue.put(request)
        request.done.wait()
        if request.error is not None:
            raise request.error
        return request.result

    def close(self) -> None:
        """停止写入线程并在安全时关闭底层存储。"""

        self._queue.put(None)
        self._thread.join(timeout=5.0)
        if not self._thread.is_alive() and hasattr(self._store, "close"):
            self._store.close()

    def _run(self) -> None:
        while True:
            request = self._queue.get()
            if request is None:
                return
            try:
                request.result = request.action()
            except BaseException as error:
                request.error = error
            finally:
                request.done.set()

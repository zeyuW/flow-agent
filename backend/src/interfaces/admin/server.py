"""本机管理 API 的 Uvicorn 生命周期封装。"""

from __future__ import annotations

import threading

import uvicorn
from fastapi import FastAPI


class AdminServer:
    """在后台线程运行并可由 ServiceApp 有序停止的 HTTP 服务器。"""

    def __init__(self, app: FastAPI, *, host: str, port: int) -> None:
        self._server = uvicorn.Server(
            uvicorn.Config(app, host=host, port=port, log_level="warning")
        )
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._server.run,
            name="admin-api",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._server.should_exit = True

    def join(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)
            if not self._thread.is_alive():
                self._thread = None

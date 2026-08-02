"""限制同一工作区只能运行一个服务进程。"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import TextIO


class WorkspaceAlreadyRunningError(RuntimeError):
    """同一工作区已经有运行实例。"""


class WorkspaceProcessLock:
    """使用内核文件锁保护工作区运行时所有权。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: TextIO | None = None

    def acquire(self) -> None:
        """非阻塞获取锁，并写入当前进程号。"""

        if self._handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.seek(0)
            owner = handle.read().strip() or "unknown"
            handle.close()
            raise WorkspaceAlreadyRunningError(
                f"工作区已有运行实例: pid={owner}"
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        os.fsync(handle.fileno())
        self._handle = handle

    def release(self) -> None:
        """释放工作区所有权；残留锁文件不会阻止下次启动。"""

        handle = self._handle
        if handle is None:
            return
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._handle = None

    def __enter__(self) -> "WorkspaceProcessLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()

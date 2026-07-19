"""主配置文件的非破坏性热重载 watcher。"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from flow_agent.config.loader import load_settings, replace_settings_cache
from flow_agent.config.settings import Settings

logger = logging.getLogger(__name__)


class ConfigWatcher:
    """配置变化通过校验后才提交到可热更新的运行时字段。"""

    def __init__(
        self,
        path: str | Path,
        on_reload: Callable[[Settings], None],
        *,
        interval_seconds: float = 1.0,
    ) -> None:
        self._path = Path(path)
        self._on_reload = on_reload
        self._interval = max(0.2, float(interval_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._revision = self._current_revision()
        self._failed_revision: tuple[int, int] | None = None

    def start(self) -> None:
        """启动配置文件轮询线程。"""

        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()

        def watch() -> None:
            while not self._stop.wait(self._interval):
                revision = self._current_revision()
                if revision == self._revision or revision == self._failed_revision:
                    continue
                previous = load_settings()
                try:
                    candidate = load_settings(force_reload=True)
                    self._on_reload(candidate)
                except Exception:
                    replace_settings_cache(previous)
                    self._failed_revision = revision
                    logger.exception("配置热重载失败，继续使用上一版运行参数")
                    continue
                self._revision = revision
                self._failed_revision = None
                logger.info("配置热重载已提交: %s", self._path)

        self._thread = threading.Thread(
            target=watch,
            name="runtime-config-watcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """停止并等待配置 watcher 退出。"""

        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    def _current_revision(self) -> tuple[int, int]:
        if not self._path.exists():
            return (0, 0)
        stat = self._path.stat()
        return (stat.st_mtime_ns, stat.st_size)

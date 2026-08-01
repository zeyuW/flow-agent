from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
import threading
from typing import Protocol

from infra.config.loader import load_config
from infra.config.schema import AppConfig


@dataclass(frozen=True, slots=True)
class PreparedConfigChange:
    """一个已准备、尚未对运行时生效的配置变更。"""

    commit: Callable[[], None]
    discard: Callable[[], None]


class ConfigApplier(Protocol):
    """把候选快照准备为可原子提交的运行时变更。"""

    def prepare(
        self,
        current: AppConfig,
        candidate: AppConfig,
    ) -> PreparedConfigChange: ...


ConfigLoader = Callable[[Path], AppConfig]
ConfigRevision = bytes | None
logger = logging.getLogger(__name__)


class ConfigWatcher:
    """按文件修订执行配置的两阶段更新。"""

    def __init__(
        self,
        path: Path,
        *,
        current: AppConfig,
        appliers: Sequence[ConfigApplier],
        loader: ConfigLoader = load_config,
    ) -> None:
        self.path = path
        self.current = current
        self.appliers = tuple(appliers)
        self.loader = loader
        self._handled_revision = _file_revision(path)

    def reload_once(self) -> bool:
        """处理一个新修订；成功提交时返回真。"""

        revision = _file_revision(self.path)
        if revision == self._handled_revision:
            return False
        self._handled_revision = revision

        try:
            candidate = self.loader(self.path)
        except Exception:
            logger.exception("候选配置加载失败，继续使用当前运行参数")
            return False

        prepared: list[PreparedConfigChange] = []
        try:
            for applier in self.appliers:
                prepared.append(applier.prepare(self.current, candidate))
        except Exception:
            for change in reversed(prepared):
                try:
                    change.discard()
                except Exception:
                    # 释放动作彼此独立，单个失败不能阻止后续候选资源清理。
                    continue
            logger.exception("候选配置准备失败，继续使用当前运行参数")
            return False

        for change in prepared:
            change.commit()
        self.current = candidate
        return True


class ReloadableConfig(Protocol):
    """可由轮询循环触发一次更新的配置对象。"""

    def reload_once(self) -> bool: ...


class ConfigWatchLoop:
    """以单一守护线程周期触发配置更新。"""

    def __init__(
        self,
        watcher: ReloadableConfig,
        *,
        interval_seconds: float = 1.0,
    ) -> None:
        self.watcher = watcher
        self.interval_seconds = max(0.01, float(interval_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """启动轮询线程；重复调用不会创建第二个线程。"""

        if self.is_running:
            return
        self._stop.clear()

        def poll() -> None:
            while not self._stop.wait(self.interval_seconds):
                try:
                    self.watcher.reload_once()
                except Exception:
                    logger.exception("配置轮询执行失败，继续使用当前运行参数")

        self._thread = threading.Thread(
            target=poll,
            name="runtime-config-watcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """停止并等待轮询线程退出。"""

        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds * 2))
            self._thread = None


def _file_revision(path: Path) -> ConfigRevision:
    try:
        return hashlib.sha256(path.read_bytes()).digest()
    except FileNotFoundError:
        return None

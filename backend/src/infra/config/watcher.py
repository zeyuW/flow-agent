from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import hashlib
from pathlib import Path
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
            return False

        for change in prepared:
            change.commit()
        self.current = candidate
        return True


def _file_revision(path: Path) -> ConfigRevision:
    try:
        return hashlib.sha256(path.read_bytes()).digest()
    except FileNotFoundError:
        return None

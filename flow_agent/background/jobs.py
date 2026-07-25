from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol


@dataclass(slots=True)
class JobSpec:
    """后台任务元数据和执行函数。

    ``interval_seconds`` 和 ``event_type`` 可同时声明；未声明时仅能由工具提交。
    默认合并同名任务，防止重复副作用；防抖窗口从上一次成功完成开始计算。
    """

    name: str
    func: Callable[[], Any]
    max_retries: int = 0
    interval_seconds: float | None = None
    event_type: type[object] | None = None
    debounce_seconds: float = 0.0
    coalesce: bool = True


class JobRegistry(Protocol):
    def register(self, job: JobSpec) -> None:
        ...

    def get(self, name: str) -> JobSpec | None:
        ...

    def unregister(self, name: str) -> None:
        ...

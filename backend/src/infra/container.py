"""顶层基础设施装配容器。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from infra.lifecycle import RuntimeService, create_runtime_service
from infra.messagebus import EventBus, MessageBus
from infra.worker import WorkerPool, WorkerSupervisor


@dataclass
class InfrastructureContainer:
    """集中管理可被业务模块共享的技术基础设施实例。"""

    message_bus: MessageBus
    event_bus: EventBus
    runtime: RuntimeService
    workers: WorkerSupervisor
    worker_pool: WorkerPool
    _closed: bool = field(default=False, init=False, repr=False)
    _close_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @classmethod
    def create(cls) -> "InfrastructureContainer":
        """创建不包含任何业务对象的基础设施容器。"""

        return cls(
            message_bus=MessageBus(),
            event_bus=EventBus(),
            runtime=create_runtime_service(),
            workers=WorkerSupervisor(),
            worker_pool=WorkerPool(),
        )

    def close(self) -> None:
        """按先停 worker、再停线程池的顺序释放资源，重复调用无副作用。"""

        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        self.workers.stop_all()
        self.worker_pool.shutdown(wait=True)

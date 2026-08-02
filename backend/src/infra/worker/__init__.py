"""后台工作基础设施：通用线程池、消费者和执行循环。"""

from infra.worker.pool import WorkerPool
from infra.worker.manager import WorkerManager

__all__ = ["WorkerManager", "WorkerPool"]

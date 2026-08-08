import threading

import pytest

from infra.worker.pool import WorkerPool


def test_worker_pool_runs_submitted_work_and_returns_result():
    with WorkerPool(max_workers=2) as pool:
        future = pool.submit(lambda: 2 + 3)

        assert future.result(timeout=1) == 5


def test_worker_pool_propagates_worker_exception():
    with WorkerPool(max_workers=1) as pool:
        future = pool.submit(lambda: 1 / 0)

        with pytest.raises(ZeroDivisionError):
            future.result(timeout=1)


def test_worker_pool_waits_for_queued_work_before_shutdown():
    started = threading.Event()
    release = threading.Event()

    with WorkerPool(max_workers=1) as pool:
        future = pool.submit(lambda: (started.set(), release.wait(1), "done")[2])
        assert started.wait(1)
        release.set()

    assert future.result(timeout=1) == "done"

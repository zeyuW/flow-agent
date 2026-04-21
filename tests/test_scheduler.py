import time

from flow_agent.proactive.scheduler import IntervalScheduler


def test_scheduler_run_once_non_reentrant():
    runs: list[int] = []

    def task() -> None:
        runs.append(1)
        time.sleep(0.05)

    scheduler = IntervalScheduler(interval_seconds=1, task=task)

    scheduler.run_once()
    scheduler.run_once()

    # sequential run_once should execute twice
    assert len(runs) == 2


def test_scheduler_start_stop_changes_status():
    scheduler = IntervalScheduler(interval_seconds=1, task=lambda: None)
    scheduler.start()
    time.sleep(0.02)
    running = scheduler.status().running
    scheduler.stop()
    stopped = scheduler.status().running

    assert running is True
    assert stopped is False

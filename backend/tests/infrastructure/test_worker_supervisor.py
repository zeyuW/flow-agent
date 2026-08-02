import threading

from infra.worker import WorkerSupervisor


def test_worker_supervisor_starts_and_stops_named_worker():
    stopped = threading.Event()
    finished = threading.Event()

    def run(stop_event: threading.Event) -> None:
        stop_event.wait()
        stopped.set()
        finished.set()

    supervisor = WorkerSupervisor()
    supervisor.register("demo", run)
    supervisor.start("demo")
    assert supervisor.running("demo") is True
    supervisor.stop("demo", timeout=1)

    assert stopped.is_set()
    assert finished.is_set()
    assert supervisor.running("demo") is False

import threading

import pytest

from modules.jobs.infra.writer import JobStoreWriter


class _Store:
    def close(self) -> None:
        pass


def test_job_store_writer_propagates_action_exception():
    writer = JobStoreWriter(_Store())

    try:
        with pytest.raises(RuntimeError, match="write failed"):
            writer.call(lambda: (_ for _ in ()).throw(RuntimeError("write failed")))
    finally:
        writer.close()


def test_job_store_writer_rejects_calls_after_close_without_blocking():
    writer = JobStoreWriter(_Store())
    writer.close()
    errors: list[BaseException] = []
    finished = threading.Event()

    def invoke() -> None:
        try:
            writer.call(lambda: None)
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()

    thread = threading.Thread(target=invoke, daemon=True)
    thread.start()

    assert finished.wait(timeout=1)
    assert errors and isinstance(errors[0], RuntimeError)

import pytest

from infra.workspace import (
    WorkspaceAlreadyRunningError,
    WorkspaceProcessLock,
)


def test_workspace_process_lock_rejects_second_owner(tmp_path):
    path = tmp_path / "runtime.lock"
    first = WorkspaceProcessLock(path)
    second = WorkspaceProcessLock(path)
    first.acquire()
    try:
        with pytest.raises(WorkspaceAlreadyRunningError):
            second.acquire()
    finally:
        first.release()

    second.acquire()
    second.release()

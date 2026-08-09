from pathlib import Path

from application.passive.infra.session_manager import ConversationContext
from application.automation.domain.models import JobSpec
from application.automation.app.runtime import AutomationRuntime, AutomationRegistry
from application.automation.infra.store import SQLiteJobStore
from infra.resilience import ErrorCategory, RetryPolicy, classify_error, retry_call


def test_turn_persistence_is_atomic_and_restores_history(tmp_path: Path):
    context = ConversationContext(db_path=tmp_path / "sessions.db")
    context.append_turn("session-1", "问题", "回答")

    restored = ConversationContext(db_path=tmp_path / "sessions.db", session_key="session-1")

    assert restored.get_full_history() == [
        {"role": "user", "content": "问题"},
        {"role": "assistant", "content": "回答"},
    ]


def test_sqlite_store_marks_interrupted_jobs_after_restart(tmp_path: Path):
    path = tmp_path / "background.db"
    first = SQLiteJobStore(path)
    run = first.start_run("demo")
    first.close()

    restored = SQLiteJobStore(path)
    rows = restored.list_runs()
    assert rows[0].run_id == run.run_id
    assert rows[0].status == "interrupted"
    assert rows[0].error_category == "interrupted"
    restored.close()


def test_background_job_records_error_category(tmp_path: Path):
    registry = AutomationRegistry()

    def fail():
        raise TimeoutError("网络超时")

    registry.register(JobSpec(name="demo", func=fail, max_retries=0))
    runtime = AutomationRuntime(
        registry=registry,
        store=SQLiteJobStore(tmp_path / "background.db"),
    )

    result = runtime.run_job("demo")

    assert result.status == "failed"
    assert result.error_category == "transient"
    runtime.stop()


def test_error_classification_and_retry_policy():
    assert classify_error(TimeoutError("timeout")).category is ErrorCategory.TRANSIENT
    assert classify_error(ValueError("bad input")).category is ErrorCategory.PERMANENT

    attempts = {"count": 0}

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise TimeoutError("temporary")
        return "ok"

    assert retry_call(
        flaky,
        policy=RetryPolicy(max_attempts=2, delay_seconds=0),
        should_retry=lambda error: classify_error(error).retryable,
    ) == "ok"


def test_retry_policy_stops_on_permanent_error():
    attempts = {"count": 0}

    def invalid():
        attempts["count"] += 1
        raise ValueError("参数错误")

    try:
        retry_call(
            invalid,
            policy=RetryPolicy(
                max_attempts=5,
                delay_seconds=0,
                retryable_only=True,
            ),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("应重新抛出不可重试错误")

    assert attempts["count"] == 1

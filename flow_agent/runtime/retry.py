import time
from dataclasses import dataclass
from typing import Callable, TypeVar


T = TypeVar("T")


@dataclass(slots=True)
class RetryPolicy:
    """Generic retry policy with linear backoff."""

    max_attempts: int = 2
    delay_seconds: float = 0.05
    backoff_factor: float = 1.5


def retry_call(
    func: Callable[[], T],
    *,
    policy: RetryPolicy,
    should_retry: Callable[[Exception], bool] | None = None,
) -> T:
    """Call function with retry and backoff."""

    attempts = 0
    delay = max(0.0, policy.delay_seconds)
    last_exc: Exception | None = None
    while attempts < max(1, policy.max_attempts):
        attempts += 1
        try:
            return func()
        except Exception as exc:
            last_exc = exc
            if attempts >= policy.max_attempts:
                break
            if should_retry is not None and not should_retry(exc):
                break
            if delay > 0:
                time.sleep(delay)
                delay *= max(1.0, policy.backoff_factor)
    assert last_exc is not None
    raise last_exc


from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

from flow_agent.runtime.errors import classify_error

T = TypeVar("T")


@dataclass(slots=True)
class RetryPolicy:
    """统一的重试参数；默认保持旧调用方的异常重试行为。"""

    max_attempts: int = 2
    delay_seconds: float = 0.05
    backoff_factor: float = 1.5
    retryable_only: bool = False


def _should_retry(
    error: Exception,
    policy: RetryPolicy,
    should_retry: Callable[[Exception], bool] | None,
) -> bool:
    if should_retry is not None:
        return should_retry(error)
    if policy.retryable_only:
        return classify_error(error).retryable
    return True


def _next_delay(delay: float, policy: RetryPolicy) -> float:
    if delay <= 0:
        return 0.0
    return delay * max(1.0, policy.backoff_factor)


def retry_call(
    func: Callable[[], T],
    *,
    policy: RetryPolicy,
    should_retry: Callable[[Exception], bool] | None = None,
) -> T:
    """同步执行函数，并按错误类别决定是否继续重试。"""

    attempts = 0
    delay = max(0.0, policy.delay_seconds)
    last_exc: Exception | None = None
    while attempts < max(1, policy.max_attempts):
        attempts += 1
        try:
            return func()
        except Exception as exc:
            last_exc = exc
            if attempts >= policy.max_attempts or not _should_retry(
                exc, policy, should_retry
            ):
                break
            if delay > 0:
                time.sleep(delay)
            delay = _next_delay(delay, policy)
    assert last_exc is not None
    raise last_exc


async def retry_async(
    func: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    should_retry: Callable[[Exception], bool] | None = None,
) -> T:
    """异步执行函数，并在等待期间保留取消语义。"""

    attempts = 0
    delay = max(0.0, policy.delay_seconds)
    last_exc: Exception | None = None
    while attempts < max(1, policy.max_attempts):
        attempts += 1
        try:
            return await func()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last_exc = exc
            if attempts >= policy.max_attempts or not _should_retry(
                exc, policy, should_retry
            ):
                break
            if delay > 0:
                await asyncio.sleep(delay)
            delay = _next_delay(delay, policy)
    assert last_exc is not None
    raise last_exc

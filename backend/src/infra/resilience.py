"""共享运行时错误分类、重试和降级策略。

业务模块只依赖这里提供的通用恢复能力，不在各自实现重复的异常分类、
退避重试和 fallback 逻辑。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
import time
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


class ErrorCategory(str, Enum):
    """统一的运行时错误类别。"""

    TRANSIENT = "transient"
    RATE_LIMIT = "rate_limit"
    AUTHENTICATION = "authentication"
    QUOTA = "quota"
    CONTEXT = "context"
    PERMANENT = "permanent"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    """错误分类结果，供重试和任务状态持久化使用。"""

    category: ErrorCategory
    retryable: bool
    code: str
    message: str


def classify_error(error: BaseException) -> ErrorInfo:
    """根据异常类型和服务端状态推导稳定的错误类别。"""

    name = type(error).__name__.lower()
    message = str(error) or type(error).__name__
    lowered = message.lower()
    status_code = getattr(error, "status_code", None)

    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        return ErrorInfo(ErrorCategory.CANCELLED, False, "cancelled", message)
    if isinstance(error, (TimeoutError, ConnectionError, OSError)):
        return ErrorInfo(ErrorCategory.TRANSIENT, True, "transient", message)
    if status_code == 429 or "rate" in name or "rate limit" in lowered:
        return ErrorInfo(ErrorCategory.RATE_LIMIT, True, "rate_limit", message)
    if "quota" in name or "quota" in lowered or "billing" in lowered:
        return ErrorInfo(ErrorCategory.QUOTA, False, "quota", message)
    if "auth" in name or "authentication" in lowered or "api key" in lowered:
        return ErrorInfo(ErrorCategory.AUTHENTICATION, False, "authentication", message)
    if "context" in name or "context window" in lowered or "token limit" in lowered:
        return ErrorInfo(ErrorCategory.CONTEXT, False, "context", message)
    if isinstance(error, (ValueError, TypeError, KeyError, PermissionError)):
        return ErrorInfo(ErrorCategory.PERMANENT, False, "permanent", message)
    if status_code is not None and int(status_code) >= 500:
        return ErrorInfo(ErrorCategory.TRANSIENT, True, "transient", message)
    return ErrorInfo(ErrorCategory.UNKNOWN, False, "unknown", message)


def with_fallback(
    primary: Callable[[], T],
    fallback: Callable[[Exception], T],
) -> T:
    """执行 primary；发生异常时调用 fallback。"""

    try:
        return primary()
    except Exception as exc:
        return fallback(exc)


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
    on_retry: Callable[[Exception, int], None] | None = None,
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
            if on_retry is not None:
                on_retry(exc, attempts)
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

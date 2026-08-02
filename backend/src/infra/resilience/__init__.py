"""共享重试、降级与错误分类基础设施。"""

from infra.resilience.errors import ErrorCategory, ErrorInfo, classify_error
from infra.resilience.fallback import with_fallback
from infra.resilience.retry import RetryPolicy, retry_async, retry_call

__all__ = [
    "ErrorCategory",
    "ErrorInfo",
    "RetryPolicy",
    "classify_error",
    "retry_async",
    "retry_call",
    "with_fallback",
]

"""运行时错误分类与恢复策略。"""

from dataclasses import dataclass
from enum import Enum


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

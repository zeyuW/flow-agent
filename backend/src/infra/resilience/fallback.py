from typing import Callable, TypeVar


T = TypeVar("T")


def with_fallback(
    primary: Callable[[], T],
    fallback: Callable[[Exception], T],
) -> T:
    """Execute primary callable and fallback on exception."""

    try:
        return primary()
    except Exception as exc:
        return fallback(exc)


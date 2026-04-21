import logging
from contextvars import ContextVar


trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)


class TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_var.get() or "-"
        return True


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] trace=%(trace_id)s %(name)s: %(message)s",
    )
    trace_filter = TraceIdFilter()
    root = logging.getLogger()
    root.addFilter(trace_filter)
    for handler in root.handlers:
        handler.addFilter(trace_filter)

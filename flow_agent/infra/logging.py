import logging
from contextvars import ContextVar
from pathlib import Path


trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)


class TraceIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_var.get() or "-"
        return True


def configure_logging(level: str = "INFO", log_path: str | Path | None = None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_path is not None:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] trace=%(trace_id)s %(name)s: %(message)s",
        handlers=handlers,
    )
    trace_filter = TraceIdFilter()
    root = logging.getLogger()
    root.addFilter(trace_filter)
    for handler in root.handlers:
        handler.addFilter(trace_filter)

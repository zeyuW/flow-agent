"""共享观测基础设施。

本模块统一提供事件信封、内存事件存储、结构化日志和轻量 trace 记录器。
业务层只通过这些稳定能力记录运行状态，不直接依赖具体日志文件实现。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
import json
import logging
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class EventEnvelope:
    event_type: str
    payload: dict[str, Any]
    timestamp: str
    correlation_id: str
    parent_id: str | None
    session_id: str | None
    trace_id: str | None

    def to_dict(self) -> dict[str, Any]:
        category = classify_event(self.event_type)
        return {
            "type": self.event_type,
            "category": category,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "parent_id": self.parent_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            **self.payload,
        }


def to_envelope(event: dict[str, Any]) -> EventEnvelope:
    event_type = str(event.get("type") or "unknown")
    payload = {k: v for k, v in event.items() if k not in _RESERVED}
    payload.setdefault("component", _infer_component(event_type))
    payload.setdefault("status", "ok")
    payload.setdefault("phase", "")
    return EventEnvelope(
        event_type=event_type,
        payload=payload,
        timestamp=str(event.get("timestamp") or utc_now_iso()),
        correlation_id=str(event.get("correlation_id") or uuid4().hex[:12]),
        parent_id=_optional_str(event.get("parent_id")),
        session_id=_optional_str(event.get("session_id")),
        trace_id=_optional_str(event.get("trace_id")),
    )


def classify_event(event_type: str) -> str:
    if event_type.startswith("turn_") or event_type in {
        "retrieval",
        "memory_organize",
        "delegation_decision",
    }:
        return "turn"
    if event_type.startswith("tool_"):
        return "tool"
    if event_type.startswith("proactive_"):
        return "proactive"
    if event_type.startswith("subagent_"):
        return "subagent"
    if event_type.startswith("job_"):
        return "job"
    return "turn"


def _infer_component(event_type: str) -> str:
    if event_type.startswith("tool_"):
        return "tool_loop"
    if event_type.startswith("proactive_"):
        return "proactive"
    if event_type.startswith("subagent_"):
        return "subagent"
    if event_type.startswith("job_"):
        return "job"
    return "turn_pipeline"


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


_RESERVED = {
    "type",
    "timestamp",
    "correlation_id",
    "parent_id",
    "session_id",
    "trace_id",
}


trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)


@contextmanager
def trace_scope(trace_id: str | None):
    """在当前任务或线程内设置 trace，并在退出时恢复上层上下文。"""

    token = trace_id_var.set(trace_id or None)
    try:
        yield
    finally:
        trace_id_var.reset(token)


class TraceIdFilter(logging.Filter):
    """将当前上下文中的 trace id 注入每条日志记录。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_var.get() or "-"
        return True


def configure_logging(level: str = "INFO", log_path: str | Path | None = None) -> None:
    """初始化控制台和可选文件日志，并统一附加 trace 字段。"""

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


@dataclass(slots=True)
class EventSnapshot:
    """按事件类别切分的一次观测快照。"""

    turns: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    proactive: list[dict[str, Any]]
    jobs: list[dict[str, Any]]
    subagents: list[dict[str, Any]]
    all_events: list[dict[str, Any]]


class EventStore:
    """统一保存规范化事件，并按类别提供快照。"""

    def __init__(self, capacity: int = 300) -> None:
        self.capacity = max(20, capacity)
        self._lock = threading.Lock()
        self._turns: deque[dict[str, Any]] = deque(maxlen=self.capacity)
        self._tools: deque[dict[str, Any]] = deque(maxlen=self.capacity)
        self._proactive: deque[dict[str, Any]] = deque(maxlen=self.capacity)
        self._jobs: deque[dict[str, Any]] = deque(maxlen=self.capacity)
        self._subagents: deque[dict[str, Any]] = deque(maxlen=self.capacity)
        self._all: deque[dict[str, Any]] = deque(maxlen=self.capacity * 3)

    def record(self, event: dict[str, Any]) -> dict[str, Any]:
        normalized = to_envelope(event).to_dict()
        bucket = classify_event(str(normalized.get("type") or ""))
        with self._lock:
            self._all.append(normalized)
            if bucket == "turn":
                self._turns.append(normalized)
            elif bucket == "tool":
                self._tools.append(normalized)
            elif bucket == "proactive":
                self._proactive.append(normalized)
            elif bucket == "job":
                self._jobs.append(normalized)
            elif bucket == "subagent":
                self._subagents.append(normalized)
        return normalized

    def snapshot(self) -> EventSnapshot:
        with self._lock:
            return EventSnapshot(
                turns=list(self._turns),
                tools=list(self._tools),
                proactive=list(self._proactive),
                jobs=list(self._jobs),
                subagents=list(self._subagents),
                all_events=list(self._all),
            )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class TraceRecorder:
    """将事件以 JSON Lines 追加写入指定 trace 文件。"""

    path: Path

    def record(self, event: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            enriched = {"ts": _utc_now_iso(), **event}
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(enriched, ensure_ascii=False) + "\n")
        except Exception:
            logger.exception("Failed to write trace event")

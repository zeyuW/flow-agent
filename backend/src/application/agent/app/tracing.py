"""面向管理 API 的安全回合追踪时间线。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading

from infra.bus.event import Event


def _format_time(value: datetime) -> str:
    """以契约要求的 UTC ISO 8601 格式输出时间。"""

    return value.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    """已经删除敏感 payload 的事件摘要。"""

    trace_id: str
    type: str
    at: str
    status: str
    summary: str
    error: str | None = None
    stage: str = "passive"
    session_id: str | None = None

    @property
    def level(self) -> str:
        return "ERROR" if self.status == "failed" else "INFO"


@dataclass(slots=True)
class TraceRecord:
    """单次 Agent 回合的聚合状态。"""

    id: str
    channel: str = "unknown"
    status: str = "running"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    events: list[TimelineEvent] = field(default_factory=list)

    @property
    def duration_ms(self) -> int:
        if self.started_at is None or self.finished_at is None:
            return 0
        return max(
            0, round((self.finished_at - self.started_at).total_seconds() * 1000)
        )

    @property
    def level(self) -> str:
        return "ERROR" if self.status == "failed" else "INFO"

    def as_summary(self) -> dict[str, object]:
        return {
            "id": self.id,
            "channel": self.channel,
            "status": self.status,
            "started_at": _format_time(self.started_at) if self.started_at else None,
            "duration_ms": self.duration_ms,
        }

    def as_detail(self) -> dict[str, object]:
        return {
            **self.as_summary(),
            "finished_at": _format_time(self.finished_at) if self.finished_at else None,
            "error": self.error,
            "events": [
                {
                    "type": event.type,
                    "at": event.at,
                    "status": event.status,
                    "summary": event.summary,
                    "error": event.error,
                }
                for event in sorted(self.events, key=lambda item: item.at)
            ],
        }


class TraceTimeline:
    """订阅生命周期事件，并保留有限的安全回合摘要。"""

    _EVENTS = {
        "before_turn": ("turn_started", "收到渠道消息", "ok"),
        "turn_started": ("turn_started", "收到渠道消息", "ok"),
        "tool_call_started": ("tool_started", "工具调用开始", "ok"),
        "tool_call_completed": ("tool_finished", "工具调用完成", "ok"),
        "subagent_started": ("subagent_started", "子 Agent 开始执行", "ok"),
        "subagent_completed": ("subagent_completed", "子 Agent 执行完成", "ok"),
        "subagent_failed": ("subagent_failed", "子 Agent 执行失败", "failed"),
        "subagent_timed_out": ("subagent_timed_out", "子 Agent 执行超时", "failed"),
        "turn_committed": ("turn_committed", "回合已提交", "ok"),
        "turn_phase_error": ("turn_failed", "回合处理失败", "failed"),
        "turn_error": ("turn_failed", "回合处理失败", "failed"),
    }

    @staticmethod
    def _stage(event_type: str) -> str:
        if event_type.startswith("tool_"):
            return "tool"
        if event_type.startswith("proactive_"):
            return "proactive"
        if event_type.startswith("subagent_"):
            return "subagent"
        if event_type.startswith("memory_"):
            return "memory"
        return "passive"

    def __init__(self, capacity: int = 300) -> None:
        self._capacity = max(20, capacity)
        self._records: dict[str, TraceRecord] = {}
        self._lock = threading.Lock()

    def record(self, event: Event) -> None:
        """记录一个事件；只读取 channel，绝不保留其他 payload。"""

        if not event.trace_id:
            return
        mapped = self._EVENTS.get(event.event_type)
        if mapped is None:
            return
        event_type, summary, event_status = mapped
        with self._lock:
            record = self._records.get(event.trace_id)
            if record is None:
                if len(self._records) >= self._capacity:
                    oldest_id = min(
                        self._records,
                        key=lambda trace_id: self._records[trace_id].started_at
                        or event.timestamp,
                    )
                    del self._records[oldest_id]
                record = TraceRecord(id=event.trace_id)
                self._records[event.trace_id] = record
            if record.started_at is None:
                record.started_at = event.timestamp
            channel = event.payload.get("channel")
            if isinstance(channel, str) and channel.strip():
                record.channel = channel.strip()
            if event.event_type == "turn_committed":
                record.status = "completed"
                record.finished_at = event.timestamp
            elif event.event_type in {"turn_phase_error", "turn_error"}:
                record.status = "failed"
                record.finished_at = event.timestamp
                record.error = "回合处理失败"
            record.events.append(
                TimelineEvent(
                    trace_id=event.trace_id,
                    type=event_type,
                    at=_format_time(event.timestamp),
                    status=event_status,
                    summary=summary,
                    error="回合处理失败" if event_status == "failed" else None,
                    stage=self._stage(event.event_type),
                    session_id=event.session_id or None,
                )
            )

    def on_event(self, event: Event) -> None:
        """兼容 EventBus 的订阅者协议。"""

        self.record(event)

    def list_traces(
        self, limit: int, status: str | None, channel: str | None
    ) -> list[TraceRecord]:
        with self._lock:
            records = list(self._records.values())
        if status is not None:
            records = [record for record in records if record.status == status]
        if channel is not None:
            records = [record for record in records if record.channel == channel]
        return sorted(
            records,
            key=lambda record: record.started_at
            or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )[:limit]

    def get_trace(self, trace_id: str) -> TraceRecord | None:
        with self._lock:
            return self._records.get(trace_id)

    def list_events(
        self, limit: int, trace_id: str | None, event_type: str | None
    ) -> list[TimelineEvent]:
        with self._lock:
            events = [
                event for record in self._records.values() for event in record.events
            ]
        if trace_id is not None:
            events = [event for event in events if event.trace_id == trace_id]
        if event_type is not None:
            events = [event for event in events if event.type == event_type]
        return sorted(events, key=lambda event: event.at, reverse=True)[:limit]

    def list_log_events(
        self,
        *,
        limit: int,
        offset: int,
        level: str | None = None,
        stage: str | None = None,
        query: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> tuple[list[TimelineEvent], int]:
        """返回管理端日志列表；只使用已脱敏的事件摘要。"""

        with self._lock:
            events = [
                event for record in self._records.values() for event in record.events
            ]
        normalized_query = (query or "").strip().lower()
        if level is not None:
            events = [event for event in events if event.level == level]
        if stage is not None:
            events = [event for event in events if event.stage == stage]
        if start_at is not None or end_at is not None:
            events = [
                event
                for event in events
                if _in_time_range(event.at, start_at, end_at)
            ]
        if normalized_query:
            events = [
                event
                for event in events
                if normalized_query in " ".join(
                    filter(None, [
                        event.type,
                        event.summary,
                        event.error,
                        event.trace_id,
                        event.session_id,
                    ])
                ).lower()
            ]
        events.sort(key=lambda event: event.at, reverse=True)
        total = len(events)
        return events[offset : offset + limit], total

    def list_log_traces(
        self,
        *,
        limit: int,
        offset: int,
        level: str | None = None,
        stage: str | None = None,
        query: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> tuple[list[TraceRecord], int]:
        """按 Trace 聚合返回管理端日志列表。"""

        with self._lock:
            records = list(self._records.values())
        normalized_query = (query or "").strip().lower()
        filtered: list[TraceRecord] = []
        for record in records:
            if level is not None and record.level != level:
                continue
            if stage is not None and not any(event.stage == stage for event in record.events):
                continue
            if start_at is not None and record.finished_at is not None and record.finished_at < start_at:
                continue
            if end_at is not None and record.started_at is not None and record.started_at > end_at:
                continue
            if normalized_query and normalized_query not in " ".join(
                filter(None, [record.id, record.channel, record.error, *(event.summary for event in record.events)])
            ).lower():
                continue
            filtered.append(record)
        filtered.sort(key=lambda record: record.started_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return filtered[offset : offset + limit], len(filtered)


def _in_time_range(
    value: str, start_at: datetime | None, end_at: datetime | None
) -> bool:
    current = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if start_at is not None and current < start_at:
        return False
    if end_at is not None and current > end_at:
        return False
    return True

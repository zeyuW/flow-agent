"""管理追踪 API 的公开响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

TraceStatus = Literal["running", "completed", "failed", "cancelled", "unknown"]


class TraceEvent(BaseModel):
    type: str
    at: str
    status: str
    summary: str
    error: str | None = None


class TraceSummary(BaseModel):
    id: str
    channel: str
    status: TraceStatus
    started_at: str | None
    duration_ms: int


class TraceDetail(TraceSummary):
    finished_at: str | None
    error: str | None = None
    events: list[TraceEvent]


class EventSummary(TraceEvent):
    trace_id: str

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


class SessionSummary(BaseModel):
    id: str
    channel: str
    external_conversation_id: str
    created_at: str
    updated_at: str
    message_count: int
    preview: str | None = None


class SessionMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: str
    tool_chain: list[str]


class SessionDetail(SessionSummary):
    messages: list[SessionMessage]

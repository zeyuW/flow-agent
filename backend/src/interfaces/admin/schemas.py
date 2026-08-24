"""管理追踪 API 的公开响应模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

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


class ScheduleSummary(BaseModel):
    id: str
    name: str
    trigger: str
    task_type: str
    message: str
    channel: str
    session_id: str
    timezone: str
    next_run_at: datetime
    interval_seconds: int | None = None
    daily_time: str | None = None
    enabled: bool
    run_count: int
    created_at: datetime | None = None
    last_error: str | None = None


class CreateSchedule(BaseModel):
    target_task_id: str
    name: str = ""
    trigger: Literal["after", "at", "daily", "every"]
    when: str
    task_type: Literal["reminder", "agent"]
    message: str


class SkillCapability(BaseModel):
    name: str
    description: str
    source: Literal["project", "installed"]
    status: Literal["available", "conflict"]
    reason: str | None = None


class ConnectorCapability(BaseModel):
    name: str
    enabled: bool = True
    connected: bool
    tools: list[str]
    description: str = ""
    related_skills: list[str] = Field(default_factory=list)
    transport: str | None = None
    protocol_version: str | None = None
    error: str | None = None


class McpServerInput(BaseModel):
    command: str = ""
    url: str | None = None
    description: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    enabled: bool = True


class McpServerEnabled(BaseModel):
    enabled: bool


class CapabilitySnapshot(BaseModel):
    skills: list[SkillCapability]
    connectors: list[ConnectorCapability]


class SkillRepository(BaseModel):
    repository_url: str


class InstallSkill(SkillRepository):
    names: list[str]


class InstalledSkillResponse(BaseModel):
    name: str


class SkillListResponse(BaseModel):
    skills: list[InstalledSkillResponse]

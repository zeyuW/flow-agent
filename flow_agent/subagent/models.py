"""Subagent data models."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class SubagentTask:
    """A delegatable task executed by a subagent."""
    task_id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    parent_trace_id: str | None = None
    status: str = "created"
    created_at: str = field(default_factory=_utc_iso)
    started_at: str | None = None
    finished_at: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass(slots=True)
class SpawnDecision:
    """Delegation decision from SpawnTool."""
    allowed: bool
    reason: str
    profile: str = "research"


# ── Spawn completion models (spec 5b) ──

@dataclass(slots=True)
class SpawnCompletionEvent:
    """Payload carried by SpawnCompletionItem."""
    job_id: str
    label: str
    task: str
    status: str        # completed | failed
    exit_reason: str   # completed | max_iterations | error
    result: str = ""
    retry_count: int = 0
    profile: str = "research"


@dataclass(slots=True)
class SpawnCompletionItem:
    """Inbound item published to MessageBus on completion (spec 5b)."""
    channel: str
    chat_id: str
    event: SpawnCompletionEvent
    decision: SpawnDecision | None = None


# ── Running job tracking (spec 2d) ──

@dataclass(slots=True)
class RunningSubagentJob:
    """Track a running background subagent job."""
    job_id: str
    label: str
    task: str
    profile: str
    origin_channel: str
    origin_chat_id: str
    task_dir: str
    retry_count: int = 0
    started_at: str = field(default_factory=_utc_iso)


# ── Job runner spec (spec 3c) ──

@dataclass(slots=True)
class AgentBackgroundJobSpec:
    """Configuration for an AgentBackgroundJobRunner."""
    job_id: str
    job_kind: str = "conversation_spawn"
    label: str = ""
    task: str = ""
    max_iterations: int = 30
    completion_mode: str = "message_bus"
    persistence_mode: str = "ephemeral"


# ── Spawn spec / profile result (spec 3e) ──

@dataclass(slots=True)
class SubagentSpec:
    """Built config for constructing a SubAgent instance."""
    tools: list[Any] = field(default_factory=list)
    tool_schemas: list[dict[str, Any]] = field(default_factory=list)
    system_prompt: str = ""
    max_iterations: int = 30

    def build(self, runtime) -> Any:
        """Build a SubAgent from this spec."""
        from flow_agent.subagent.sub_agent import SubAgent
        return SubAgent(
            tools=self.tools,
            tool_schemas=self.tool_schemas,
            system_prompt=self.system_prompt,
            max_iterations=self.max_iterations,
            llm_client=getattr(runtime, 'llm_client', None),
        )


@dataclass(slots=True)
class JobRunResult:
    """Standardized result from AgentBackgroundJobRunner.run()."""
    job_id: str
    status: str       # completed | failed | error
    exit_reason: str  # completed | max_iterations | error
    result_summary: str = ""
    error: str | None = None

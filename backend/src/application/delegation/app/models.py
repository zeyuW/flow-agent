"""委托应用层的执行配置和结果对象。"""

from dataclasses import dataclass, field
from typing import Any


SUBAGENT_STATUSES = frozenset(
    {"completed", "failed", "timed_out", "cancelled"}
)


@dataclass(slots=True)
class SubagentResult:
    """Subagent 对 Lead Agent 暴露的稳定结果协议。"""

    task_id: str
    status: str
    summary: str = ""
    error: str | None = None
    steps: int = 0

    def __post_init__(self) -> None:
        if self.status not in SUBAGENT_STATUSES:
            raise ValueError(f"不支持的 Subagent 状态: {self.status}")
        self.steps = max(0, int(self.steps))

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "summary": self.summary,
            "error": self.error,
            "steps": self.steps,
        }


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
        from application.delegation.app.sub_agent import SubAgent
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

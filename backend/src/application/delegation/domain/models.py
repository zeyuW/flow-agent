"""委托模块的领域记录。"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_iso() -> str:
    """生成统一的 UTC 时间字符串。"""

    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class SubagentTask:
    """一项可交给子代理执行的后台任务。"""

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
    """是否允许创建子代理的决策。"""

    allowed: bool
    reason: str
    profile: str = "research"


@dataclass(slots=True)
class SpawnCompletionEvent:
    """子代理完成事件的领域载荷。"""

    job_id: str
    label: str
    task: str
    status: str
    exit_reason: str
    result: str = ""
    retry_count: int = 0
    profile: str = "research"


@dataclass(slots=True)
class SpawnCompletionItem:
    """准备重新投递到原会话的完成事件。"""

    channel: str
    chat_id: str
    event: SpawnCompletionEvent
    decision: SpawnDecision | None = None


@dataclass(slots=True)
class RunningSubagentJob:
    """正在运行的子代理任务。"""

    job_id: str
    label: str
    task: str
    profile: str
    origin_channel: str
    origin_chat_id: str
    origin_session_id: str
    task_dir: str
    retry_count: int = 0
    started_at: str = field(default_factory=_utc_iso)

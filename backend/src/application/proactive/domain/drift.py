"""主动漂移能力的领域模型。"""

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass
class DriftSkill:
    """用户定义的漂移技能。"""

    name: str
    description: str = ""
    requires_mcp: list[str] = field(default_factory=list)
    state: dict = field(default_factory=dict)
    path: str = ""
    instructions: str = ""


@dataclass
class DriftRun:
    """单次漂移运行记录。"""

    run_id: str = field(default_factory=lambda: uuid4().hex)
    skill_name: str = ""
    action: str = ""
    result: str = ""
    status: str = "completed"
    timestamp: str = ""
    finished_at: str = ""
    error: str = ""


@dataclass
class DriftTick:
    """一次漂移执行的上下文。"""

    skills: list[DriftSkill] = field(default_factory=list)
    runs: list[DriftRun] = field(default_factory=list)
    message: str = ""
    finished: bool = False

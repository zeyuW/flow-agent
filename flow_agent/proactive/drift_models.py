"""漂移模式数据模型。"""

from dataclasses import dataclass, field


@dataclass
class DriftSkill:
    """用户定义的漂移技能。"""

    name: str
    description: str = ""
    requires_mcp: list[str] = field(default_factory=list)
    state: dict = field(default_factory=dict)
    path: str = ""


@dataclass
class DriftRun:
    """单次漂移运行记录。"""

    skill_name: str = ""
    action: str = ""
    result: str = ""
    timestamp: str = ""


@dataclass
class DriftTick:
    """一次漂移执行的上下文。"""

    skills: list[DriftSkill] = field(default_factory=list)
    runs: list[DriftRun] = field(default_factory=list)
    message: str = ""
    finished: bool = False

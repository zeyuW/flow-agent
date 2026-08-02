"""用户画像抽取器：从用户消息中识别可长期沉淀的信息。"""

from dataclasses import dataclass
import re

from modules.memory.domain.profile_models import UserProfile


@dataclass(slots=True)
class ExtractedProfileItem:
    """可写入长期记忆的一条结构化用户信息。"""

    memory_type: str
    summary: str
    source_label: str
    emotional_weight: int = 1


_CLAUSE_SPLIT_RE = re.compile(r"[。！？!?；;，,\n\r]+")
_EXPLICIT_PREFIX_RE = re.compile(
    r"^(?:请记住|记住|记录|保存)?\s*"
    r"(事实|偏好|需求|任务|待办|规则|约束)\s*[:：]\s*(.+)$"
)

_EXPLICIT_TYPE_MAP = {
    "事实": ("fact", "fact"),
    "偏好": ("preference", "preference"),
    "需求": ("need", "need"),
    "任务": ("task", "task"),
    "待办": ("task", "task"),
    "规则": ("procedure", "procedure"),
    "约束": ("procedure", "procedure"),
}

_IDENTITY_KEYWORDS = ("我叫", "我的名字", "称呼我", "我是", "我的身份")
_FACT_KEYWORDS = (
    "事实",
    "我在",
    "我住",
    "我来自",
    "我的工作",
    "我的职业",
    "我的项目",
    "我使用",
    "我用",
)
_PREFERENCE_KEYWORDS = (
    "喜欢",
    "不喜欢",
    "偏好",
    "更喜欢",
    "更倾向",
    "习惯",
    "回答风格",
    "语气",
    "以后请",
    "希望你以后",
)
_PROCEDURE_KEYWORDS = (
    "必须",
    "务必",
    "严禁",
    "不得",
    "禁止",
    "规则",
    "约束",
    "每次",
    "始终",
    "以后都",
    "默认",
)
_TASK_KEYWORDS = (
    "帮我",
    "请帮",
    "实现",
    "修改",
    "修复",
    "分析",
    "写一份",
    "创建",
    "添加",
    "删除",
    "测试",
    "检查",
    "完成",
    "提醒",
    "待办",
    "任务",
)
_NEED_KEYWORDS = (
    "需求",
    "需要",
    "想要",
    "我要",
    "希望",
    "期望",
    "目标",
    "计划",
    "打算",
)


class ProfileExtractor:
    """从对话历史中抽取用户事实、偏好、需求和任务。"""

    def extract(self, messages: list[dict[str, str]]) -> UserProfile:
        """抽取聚合后的用户画像。"""
        profile = UserProfile()
        for msg in messages:
            if msg.get("role") != "user":
                continue
            text = (msg.get("content") or "").strip()
            if not text:
                continue
            for item in self.extract_memory_items(text):
                self._append_to_profile(profile, item)
        return profile

    def extract_memory_items(self, text: str) -> list[ExtractedProfileItem]:
        """从单条用户消息中抽取可写入长期记忆的条目。"""
        items: list[ExtractedProfileItem] = []
        seen: set[tuple[str, str]] = set()
        for clause in _split_clauses(text):
            item = self._classify_clause(clause)
            if item is None:
                continue
            key = (item.memory_type, item.summary)
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
        return items

    def _classify_clause(self, clause: str) -> ExtractedProfileItem | None:
        explicit = _EXPLICIT_PREFIX_RE.match(clause)
        if explicit:
            memory_type, source_label = _EXPLICIT_TYPE_MAP[explicit.group(1)]
            summary = _summary_for(memory_type, explicit.group(2).strip())
            return ExtractedProfileItem(memory_type, summary, source_label, 2)

        if _contains_any(clause, _PROCEDURE_KEYWORDS):
            return ExtractedProfileItem(
                "procedure",
                _summary_for("procedure", clause),
                "procedure",
                2,
            )
        if _contains_any(clause, _PREFERENCE_KEYWORDS):
            return ExtractedProfileItem(
                "preference",
                _summary_for("preference", clause),
                "preference",
                2,
            )
        if _contains_any(clause, _TASK_KEYWORDS):
            return ExtractedProfileItem(
                "task",
                _summary_for("task", clause),
                "task",
                1,
            )
        if _contains_any(clause, _NEED_KEYWORDS):
            return ExtractedProfileItem(
                "need",
                _summary_for("need", clause),
                "need",
                1,
            )
        if _contains_any(clause, _IDENTITY_KEYWORDS):
            return ExtractedProfileItem(
                "fact",
                _summary_for("fact", clause),
                "identity",
                2,
            )
        if _contains_any(clause, _FACT_KEYWORDS):
            return ExtractedProfileItem(
                "fact",
                _summary_for("fact", clause),
                "fact",
                1,
            )
        return None

    def _append_to_profile(self, profile: UserProfile, item: ExtractedProfileItem) -> None:
        if item.source_label == "identity":
            profile.identity.append(item.summary)
        elif item.memory_type == "fact":
            profile.fact.append(item.summary)
        elif item.memory_type == "preference":
            profile.preference.append(item.summary)
        elif item.memory_type == "need":
            profile.need.append(item.summary)
            if _contains_any(item.summary, ("目标", "计划", "打算")):
                profile.goal.append(item.summary)
        elif item.memory_type == "task":
            profile.task.append(item.summary)
        elif item.memory_type == "procedure":
            profile.constraint.append(item.summary)
        if _contains_any(item.summary, ("完成", "里程碑")):
            profile.milestone.append(item.summary)
        if _contains_any(item.summary, ("每天", "习惯")):
            profile.routine.append(item.summary)


def _split_clauses(text: str) -> list[str]:
    """按常见中文断句符切分，并保留足够自包含的短句。"""
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return []
    clauses = [part.strip() for part in _CLAUSE_SPLIT_RE.split(normalized)]
    return [clause[:160] for clause in clauses if len(clause.strip()) >= 2]


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _summary_for(memory_type: str, text: str) -> str:
    """生成以用户为主体的记忆摘要，避免注入提示词后主语混乱。"""
    body = re.sub(r"\s+", " ", text).strip()
    if body.startswith("我的"):
        body = "用户的" + body[2:]
    elif body.startswith("我"):
        body = "用户" + body[1:]
    elif body.startswith("帮我"):
        body = "用户请求助手" + body[2:]
    elif body.startswith("请帮我"):
        body = "用户请求助手" + body[3:]
    elif not body.startswith("用户"):
        labels = {
            "fact": "用户事实",
            "preference": "用户偏好",
            "need": "用户需求",
            "task": "用户任务",
            "procedure": "用户规则",
        }
        body = f"{labels.get(memory_type, '用户信息')}：{body}"
    return body

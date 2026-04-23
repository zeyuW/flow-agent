from flow_agent.memory.profile_models import UserProfile


class ProfileExtractor:
    """Extract structured profile facts from conversation history."""

    def extract(self, messages: list[dict[str, str]]) -> UserProfile:
        profile = UserProfile()
        for msg in messages:
            if msg.get("role") != "user":
                continue
            text = (msg.get("content") or "").strip()
            if not text:
                continue
            if "我叫" in text:
                profile.identity.append(text)
            if "喜欢" in text:
                profile.preference.append(text)
            if "目标" in text or "计划" in text:
                profile.goal.append(text)
            if "不能" in text or "限制" in text:
                profile.constraint.append(text)
            if "完成" in text or "里程碑" in text:
                profile.milestone.append(text)
            if "每天" in text or "习惯" in text:
                profile.routine.append(text)
        return profile


class MessageQualityChecker:
    """Check message quality before proactive send."""

    def check(self, content: str) -> tuple[bool, str]:
        text = (content or "").strip()
        if not text:
            return False, "empty"
        if len(text) < 6:
            return False, "too_short"
        if len(text) > 400:
            return False, "too_long"
        return True, "ok"


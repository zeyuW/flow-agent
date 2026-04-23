import threading
import time
from dataclasses import dataclass, field


@dataclass(slots=True)
class GuardDecision:
    allowed: bool
    reason: str


@dataclass(slots=True)
class ToolGuard:
    """Tool whitelist/blacklist and simple file path risk guard."""

    whitelist: set[str] | None = None
    blacklist: set[str] = field(default_factory=set)
    blocked_path_keywords: tuple[str, ...] = (".ssh", ".aws", "id_rsa", "credentials")

    def check_tool(self, tool_name: str) -> GuardDecision:
        if tool_name in self.blacklist:
            return GuardDecision(False, "tool_blacklisted")
        if self.whitelist is not None and tool_name not in self.whitelist:
            return GuardDecision(False, "tool_not_whitelisted")
        return GuardDecision(True, "ok")

    def check_tool_input(self, tool_name: str, tool_input: dict[str, str]) -> GuardDecision:
        if tool_name != "read_file":
            return GuardDecision(True, "ok")
        path = (tool_input.get("path") or "").strip().lower()
        if any(keyword in path for keyword in self.blocked_path_keywords):
            return GuardDecision(False, "filesystem_risky_path")
        return GuardDecision(True, "ok")


class SubagentConcurrencyGuard:
    """Limit max subagent concurrent tasks."""

    def __init__(self, max_concurrency: int = 2) -> None:
        self.max_concurrency = max(1, max_concurrency)
        self._running = 0
        self._lock = threading.Lock()

    def acquire(self) -> GuardDecision:
        with self._lock:
            if self._running >= self.max_concurrency:
                return GuardDecision(False, "subagent_concurrency_limited")
            self._running += 1
        return GuardDecision(True, "ok")

    def release(self) -> None:
        with self._lock:
            self._running = max(0, self._running - 1)


class BackgroundReentryGuard:
    """Protect background job reentry and timeout."""

    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = max(0.1, timeout_seconds)
        self._running_since: float | None = None
        self._lock = threading.Lock()

    def acquire(self) -> GuardDecision:
        now = time.time()
        with self._lock:
            if self._running_since is not None and (now - self._running_since) < self.timeout_seconds:
                return GuardDecision(False, "background_reentry_blocked")
            self._running_since = now
        return GuardDecision(True, "ok")

    def release(self) -> None:
        with self._lock:
            self._running_since = None


class SourceIsolationGuard:
    """Validate source metadata before ingesting records."""

    @staticmethod
    def check_source_name(source_name: str) -> GuardDecision:
        if not source_name.strip():
            return GuardDecision(False, "empty_source_name")
        return GuardDecision(True, "ok")


class ProactiveFrequencyGuard:
    """Extra frequency cap to avoid too frequent proactive sends."""

    def __init__(self, min_interval_seconds: int = 30) -> None:
        self.min_interval_seconds = max(0, min_interval_seconds)
        self._last_ok_at: float | None = None

    def check(self) -> GuardDecision:
        if self.min_interval_seconds <= 0:
            return GuardDecision(True, "ok")
        now = time.time()
        if self._last_ok_at is not None and (now - self._last_ok_at) < self.min_interval_seconds:
            return GuardDecision(False, "proactive_rate_limited")
        self._last_ok_at = now
        return GuardDecision(True, "ok")


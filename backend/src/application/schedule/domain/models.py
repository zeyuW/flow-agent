"""定时任务领域模型和不依赖外部设施的时间规则。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_TIMEZONE = "Asia/Shanghai"
_DURATION_RE = re.compile(
    r"^(?:(?P<days>\d+)d)?(?:(?P<hours>\d+)h)?"
    r"(?:(?P<minutes>\d+)m)?(?:(?P<seconds>\d+)s)?$"
)


@dataclass(slots=True)
class ScheduledTask:
    """一条可持久化并恢复执行的用户定时任务。"""

    id: str
    name: str
    trigger: str
    task_type: str
    message: str
    channel: str
    session_id: str
    chat_id: str
    timezone: str
    next_run_at: datetime
    interval_seconds: int | None = None
    daily_time: str | None = None
    enabled: bool = True
    run_count: int = 0
    created_at: datetime | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, object]:
        """转换为工具和日志可安全输出的结构。"""

        return {
            "id": self.id,
            "name": self.name,
            "trigger": self.trigger,
            "task_type": self.task_type,
            "message": self.message,
            "channel": self.channel,
            "session_id": self.session_id,
            "timezone": self.timezone,
            "next_run_at": self.next_run_at.isoformat(),
            "interval_seconds": self.interval_seconds,
            "daily_time": self.daily_time,
            "enabled": self.enabled,
            "run_count": self.run_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_error": self.last_error,
        }


def parse_duration(value: str) -> timedelta:
    """解析 30s、5m、2h、1d2h 等紧凑时长。"""

    match = _DURATION_RE.fullmatch(value.strip().lower())
    if match is None or not any(match.groupdict().values()):
        raise ValueError("无效时长，示例：30s、5m、2h、1d2h")
    parts = {name: int(raw or 0) for name, raw in match.groupdict().items()}
    duration = timedelta(**parts)
    if duration.total_seconds() <= 0:
        raise ValueError("时长必须大于 0")
    return duration


def normalize_clock_time(value: str) -> str:
    """校验并规范 HH:MM 时刻。"""

    try:
        parsed = datetime.strptime(value.strip(), "%H:%M")
    except ValueError as exc:
        raise ValueError("每日任务时间必须使用 HH:MM，例如 08:30") from exc
    return parsed.strftime("%H:%M")


def parse_at(value: str, tz: ZoneInfo, now: datetime) -> datetime:
    """解析下一次本地时刻或带日期的 ISO 8601 时间。"""

    clean = value.strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", clean):
        clock = datetime.strptime(clean, "%H:%M").time()
        result = now.replace(
            hour=clock.hour,
            minute=clock.minute,
            second=0,
            microsecond=0,
        )
        if result <= now:
            result += timedelta(days=1)
        return result
    try:
        result = datetime.fromisoformat(clean.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("无法解析时间，请使用 HH:MM 或 ISO 8601") from exc
    if result.tzinfo is None:
        result = result.replace(tzinfo=tz)
    result = result.astimezone(tz)
    if result <= now:
        raise ValueError("指定时间必须晚于当前时间")
    return result


def load_timezone(name: str) -> ZoneInfo:
    """加载时区并把底层异常转换成领域校验错误。"""

    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"无效时区: {name}") from exc

"""定时任务应用服务：编排创建、恢复、执行和停止。"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from application.schedule.domain.models import (
    DEFAULT_TIMEZONE,
    ScheduledTask,
    load_timezone,
    normalize_clock_time,
    parse_at,
    parse_duration,
)
from application.schedule.infra.store import ScheduledTaskStore
from infra.bus.message import OutboundDispatch
from infra.bus.types import InboundMessage, MessageSender, SendMessage

logger = logging.getLogger(__name__)


class SchedulerService:
    """创建、恢复并到期投递用户提醒和 Agent 任务。"""

    def __init__(
        self,
        *,
        store_path: str | Path,
        inbound_queue=None,
        message_sender: MessageSender | None = None,
        outbound_port=None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = ScheduledTaskStore(store_path)
        self.inbound_queue = inbound_queue
        self.message_sender = message_sender
        self.outbound_port = outbound_port
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def create_task(
        self,
        *,
        trigger: str,
        when: str,
        task_type: str,
        message: str,
        channel: str,
        session_id: str,
        chat_id: str,
        timezone_name: str = DEFAULT_TIMEZONE,
        name: str = "",
    ) -> ScheduledTask:
        """校验触发规则并创建一条持久化任务。"""

        if trigger not in {"after", "at", "daily", "every"}:
            raise ValueError("trigger 必须是 after、at、daily 或 every")
        if task_type not in {"reminder", "agent"}:
            raise ValueError("task_type 必须是 reminder 或 agent")
        if not message.strip():
            raise ValueError("message 不能为空")
        if not session_id or not channel:
            raise ValueError("缺少当前会话上下文")
        tz = load_timezone(timezone_name)
        now = self._aware_now().astimezone(tz)
        interval_seconds: int | None = None
        daily_time: str | None = None
        if trigger == "after":
            next_run = now + parse_duration(when)
        elif trigger == "at":
            next_run = parse_at(when, tz, now)
        elif trigger == "daily":
            daily_time = normalize_clock_time(when)
            next_run = parse_at(daily_time, tz, now)
        else:
            interval = parse_duration(when)
            interval_seconds = int(interval.total_seconds())
            if interval_seconds < 1:
                raise ValueError("周期必须至少为 1 秒")
            next_run = now + interval
        task = ScheduledTask(
            id=uuid4().hex[:12],
            name=name.strip() or message.strip()[:40],
            trigger=trigger,
            task_type=task_type,
            message=message.strip(),
            channel=channel,
            session_id=session_id,
            chat_id=chat_id or session_id,
            timezone=timezone_name,
            next_run_at=next_run.astimezone(timezone.utc),
            interval_seconds=interval_seconds,
            daily_time=daily_time,
            created_at=self._aware_now(),
        )
        self.store.add(task)
        self._wake.set()
        logger.info(
            "定时任务已创建: id=%s trigger=%s next_run_at=%s type=%s",
            task.id,
            task.trigger,
            task.next_run_at.isoformat(),
            task.task_type,
        )
        return task

    def list_tasks(self, session_id: str) -> list[ScheduledTask]:
        return self.store.list_for_session(session_id)

    def list_all_tasks(self) -> list[ScheduledTask]:
        """读取全部任务，供本机管理控制台展示。"""

        return self.store.list_all()

    def get_task_by_id(self, task_id: str) -> ScheduledTask | None:
        """读取任务的投递目标，供本机管理控制台创建同会话任务。"""

        return self.store.get_by_id(task_id)

    def cancel_task(self, task_id: str, session_id: str) -> bool:
        cancelled = self.store.cancel(task_id, session_id)
        if cancelled:
            self._wake.set()
        return cancelled

    def cancel_task_by_id(self, task_id: str) -> bool:
        """停止指定任务，供本机管理控制台调用。"""

        cancelled = self.store.cancel_by_id(task_id)
        if cancelled:
            self._wake.set()
        return cancelled

    def resume_task_by_id(self, task_id: str) -> bool:
        """恢复每天或固定间隔的任务，并重新计算下一次执行时间。"""

        task = self.store.get_by_id(task_id)
        if task is None or task.enabled or task.trigger not in {"daily", "every"}:
            return False
        next_run = self._next_run(task, self._aware_now(), failed=False)
        if next_run is None:
            return False
        resumed = self.store.resume(task_id, next_run)
        if resumed:
            self._wake.set()
        return resumed

    def start(self) -> None:
        """启动唯一的后台调度线程。"""

        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._wake.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="scheduled-task-runtime",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """停止调度线程并等待当前轮结束。"""

        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def run_due_once(self) -> int:
        """执行当前全部到期任务，供后台循环和测试复用。"""

        now = self._aware_now()
        tasks = self.store.due(now)
        for task in tasks:
            error: str | None = None
            try:
                self._dispatch(task)
            except Exception as exc:
                error = str(exc)
                logger.exception("定时任务投递失败: id=%s", task.id)
            next_run = self._next_run(task, now, failed=error is not None)
            self.store.complete(task, next_run_at=next_run, error=error)
        return len(tasks)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            self.run_due_once()
            due_at = self.store.next_due_at()
            if due_at is None:
                timeout = 30.0
            else:
                timeout = max(
                    0.1,
                    min(30.0, (due_at - self._aware_now()).total_seconds()),
                )
            self._wake.wait(timeout)
            self._wake.clear()

    def _dispatch(self, task: ScheduledTask) -> None:
        if task.task_type == "agent":
            if self.inbound_queue is None:
                raise RuntimeError("Agent 入站队列未配置")
            self.inbound_queue.publish(
                InboundMessage(
                    channel=task.channel,
                    session_id=task.session_id,
                    text=(
                        "[系统定时任务已到期；这是执行指令，不要再次安排任务]\n"
                        f"任务：{task.message}"
                    ),
                    chat_id=task.chat_id,
                    metadata={
                        "scheduled_task": True,
                        "scheduled_task_id": task.id,
                    },
                )
            )
            return
        if self.message_sender is None and self.outbound_port is None:
            raise RuntimeError("出站消息端口未配置")
        metadata: dict[str, object] = {
            "scheduled_task": True,
            "scheduled_task_id": task.id,
            "proactive": True,
        }
        if self.message_sender is not None:
            result = self.message_sender.send(
                SendMessage(
                    channel=task.channel,
                    conversation_id=task.session_id,
                    recipient_id=task.chat_id,
                    text=task.message,
                    message_id=task.id,
                    metadata=metadata,
                )
            )
            if not result.accepted:
                raise RuntimeError(result.error or "消息未进入可靠队列")
            return
        assert self.outbound_port is not None
        self.outbound_port.send(
            OutboundDispatch(
                channel=task.channel,
                session_id=task.session_id,
                text=task.message,
                chat_id=task.chat_id,
                metadata=metadata,
            )
        )

    def _next_run(
        self,
        task: ScheduledTask,
        now: datetime,
        *,
        failed: bool,
    ) -> datetime | None:
        if failed:
            return now + timedelta(seconds=60)
        if task.trigger == "daily" and task.daily_time:
            tz = load_timezone(task.timezone)
            return parse_at(task.daily_time, tz, now.astimezone(tz)).astimezone(
                timezone.utc
            )
        if task.trigger == "every" and task.interval_seconds:
            next_run = task.next_run_at
            interval = timedelta(seconds=task.interval_seconds)
            while next_run <= now:
                next_run += interval
            return next_run
        return None

    def _aware_now(self) -> datetime:
        value = self._now_fn()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

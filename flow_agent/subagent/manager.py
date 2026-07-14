"""SubagentManager: async spawn, background execution, MessageBus completion (spec 1-5)."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from flow_agent.subagent.models import (
    AgentBackgroundJobSpec,
    JobRunResult,
    RunningSubagentJob,
    SpawnCompletionEvent,
    SpawnCompletionItem,
    SpawnDecision,
    SubagentSpec,
)
from flow_agent.subagent.runner import AgentBackgroundJobRunner
from flow_agent.subagent.profiles import build_spawn_spec, PROFILE_RESEARCH

logger = logging.getLogger(__name__)
_SPAWN_MAX_ITERATIONS = 30


class SubagentManager:
    """Manages subagent lifecycle: spawn, background execution, completion notification."""

    def __init__(
        self,
        *,
        tasks_path: Path,
        message_bus: Any = None,
        llm_client: Any = None,
    ) -> None:
        self.tasks_path = tasks_path
        self._bus = message_bus
        self._llm = llm_client
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._running_jobs: dict[str, RunningSubagentJob] = {}
        self.max_concurrency = 2

    def create_task(self, kind: str, payload: dict, *, parent_trace_id: str | None = None) -> Any:
        from flow_agent.subagent.models import SubagentTask
        task = SubagentTask(
            task_id=uuid4().hex[:12],
            kind=kind,
            payload=payload,
            parent_trace_id=parent_trace_id,
        )
        self._persist(task)
        return task

    def run_task(self, task, executor) -> None:
        import threading
        def _run():
            task.status = "running"
            task.started_at = datetime.now(timezone.utc).isoformat()
            self._persist(task)
            try:
                result = executor(task)
                task.status = "completed"
                task.result = result
                task.error = None
            except Exception as exc:
                task.status = "failed"
                task.error = str(exc)
            finally:
                task.finished_at = datetime.now(timezone.utc).isoformat()
                self._persist(task)
        threading.Thread(target=_run, daemon=True).start()

    def list_recent_tasks(self, limit: int = 10) -> list:
        if not self.tasks_path.exists():
            return []
        lines = self.tasks_path.read_text(encoding="utf-8").splitlines()
        rows = []
        for line in lines[-max(1, limit):]:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def _persist(self, task) -> None:
        try:
            self.tasks_path.parent.mkdir(parents=True, exist_ok=True)
            with self.tasks_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "task_id": task.task_id,
                    "kind": task.kind,
                    "payload": task.payload,
                    "parent_trace_id": task.parent_trace_id,
                    "status": task.status,
                    "created_at": task.created_at if isinstance(task.created_at, str) else task.created_at.isoformat(),
                    "started_at": task.started_at if isinstance(task.started_at, str) else (task.started_at.isoformat() if task.started_at else None),
                    "finished_at": task.finished_at if isinstance(task.finished_at, str) else (task.finished_at.isoformat() if task.finished_at else None),
                    "result": task.result,
                    "error": task.error,
                }, ensure_ascii=False) + "\n")
        except Exception:
            logger.exception("failed persisting subagent task")


    # ── Spawn (spec 1c, 2) ──

    async def spawn(
        self,
        *,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "default",
        profile: str = PROFILE_RESEARCH,
        retry_count: int = 0,
        decision: SpawnDecision | None = None,
    ) -> str:
        """Create a background subagent task, return immediately (spec 2a-2e)."""
        if len(self._running_tasks) >= self.max_concurrency:
            return f"已到达最大并行数 ({self.max_concurrency})，请稍后再试。"

        job_id = uuid4().hex[:12]
        display_label = label or task[:40]

        # 2b: tracing
        self._trace(job_id, "started", {
            "label": display_label,
            "origin_channel": origin_channel,
            "origin_chat_id": origin_chat_id,
            "profile": profile,
        })

        # 2c: create async background task
        bg_task = asyncio.create_task(
            self._run_subagent(
                job_id=job_id,
                task=task,
                label=display_label,
                origin_channel=origin_channel,
                origin_chat_id=origin_chat_id,
                profile=profile,
                retry_count=retry_count,
            ),
            name=f"spawn:{job_id}",
        )

        # 2d: register
        self._running_tasks[job_id] = bg_task
        self._running_jobs[job_id] = RunningSubagentJob(
            job_id=job_id,
            label=display_label,
            task=task,
            profile=profile,
            origin_channel=origin_channel,
            origin_chat_id=origin_chat_id,
            task_dir=str(self.tasks_path.parent),
            retry_count=retry_count,
        )

        # 2e: immediate confirmation
        return (
            f"已创建后台任务「{display_label}」（job_id={job_id}）。"
            "不要等待其完成；请直接向用户说明你已开始处理，完成后会继续回复。"
        )

    # ── Sync spawn (spec 1d) ──

    async def spawn_sync(
        self,
        *,
        task: str,
        label: str | None = None,
        profile: str = PROFILE_RESEARCH,
    ) -> str:
        """Spawn a subagent and block until complete (spec 1d)."""
        spec = build_spawn_spec(profile=profile, max_iterations=_SPAWN_MAX_ITERATIONS)
        agent = spec.build(runtime=self)
        return await agent.run(task)

    # ── Background execution (spec 3) ──

    async def _run_subagent(
        self,
        *,
        job_id: str,
        task: str,
        label: str,
        origin_channel: str,
        origin_chat_id: str,
        profile: str,
        retry_count: int = 0,
    ) -> None:
        """Background task: build SubAgent, run, announce result (spec 3a)."""
        try:
            # 3b, 3c: build runner with agent factory
            spec = build_spawn_spec(profile=profile, max_iterations=_SPAWN_MAX_ITERATIONS)
            runner = AgentBackgroundJobRunner(
                lambda: spec.build(runtime=self)
            )
            job_spec = AgentBackgroundJobSpec(
                job_id=job_id,
                label=label,
                task=task,
                max_iterations=_SPAWN_MAX_ITERATIONS,
                completion_mode="message_bus",
            )

            # 3d: execute
            result = await runner.run(job_spec)

            # 5a: announce completion via MessageBus
            await self._announce_result(
                job_id=job_id,
                label=label,
                task=task,
                origin_channel=origin_channel,
                origin_chat_id=origin_chat_id,
                status=result.status,
                exit_reason=result.exit_reason,
                result=result.result_summary,
                profile=profile,
                retry_count=retry_count,
            )
        except Exception as exc:
            logger.exception("[spawn] _run_subagent failed job_id=%s", job_id)
            await self._announce_result(
                job_id=job_id, label=label, task=task,
                origin_channel=origin_channel, origin_chat_id=origin_chat_id,
                status="error", exit_reason="error",
                result=f"error: {exc}", profile=profile, retry_count=retry_count,
            )
        finally:
            self._running_tasks.pop(job_id, None)
            self._running_jobs.pop(job_id, None)

    # ── Completion notification via MessageBus (spec 5) ──

    async def _announce_result(
        self,
        *,
        job_id: str,
        label: str,
        task: str,
        origin_channel: str,
        origin_chat_id: str,
        status: str,
        exit_reason: str,
        result: str,
        profile: str,
        retry_count: int = 0,
        decision: SpawnDecision | None = None,
    ) -> None:
        """Publish spawn completion event to MessageBus (spec 5a-5c)."""
        if self._bus is None:
            logger.warning("[spawn] no message bus, cannot announce completion")
            return

        event = SpawnCompletionEvent(
            job_id=job_id,
            label=label,
            task=task,
            status=status,
            exit_reason=exit_reason,
            result=result,
            retry_count=retry_count,
            profile=profile,
        )

        item = SpawnCompletionItem(
            channel=origin_channel,
            chat_id=origin_chat_id,
            event=event,
            decision=decision,
        )

        # 5c: publish as inbound message
        from flow_agent.channels.models import InboundMessage
        msg = InboundMessage(
            channel=origin_channel,
            session_id=origin_chat_id,
            text=json.dumps({
                "type": "spawn_completion",
                "job_id": job_id,
                "label": label,
                "status": status,
                "result": result[:500],
            }, ensure_ascii=False),
        )
        self._bus.publish_inbound(msg)  # 5d-5e: MessageBus → AgentLoop consumes
        logger.info("[spawn] completion announced: job_id=%s status=%s", job_id, status)

    @property
    def running_count(self) -> int:
        return len(self._running_tasks)

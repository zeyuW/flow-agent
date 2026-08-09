"""管理子代理的创建、后台执行、状态记录和完成通知。"""

import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from application.delegation.app.models import (
    AgentBackgroundJobSpec,
    JobRunResult,
    SubagentSpec,
)
from application.delegation.app.runner import AgentBackgroundJobRunner
from application.delegation.app.profiles import build_spawn_spec, PROFILE_RESEARCH
from application.delegation.domain.models import (
    RunningSubagentJob,
    SpawnCompletionEvent,
    SpawnCompletionItem,
    SpawnDecision,
    SubagentTask,
)
from application.delegation.infra.store import JsonlTaskStore

logger = logging.getLogger(__name__)
_SPAWN_MAX_ITERATIONS = 30
_COMPLETION_RESULT_MAX_CHARS = 12_000


class SubagentManager:
    """统一管理子代理生命周期，并为同步工具提供持久事件循环。"""

    def __init__(
        self,
        *,
        task_store: JsonlTaskStore,
        message_bus: Any = None,
        llm_client: Any = None,
    ) -> None:
        self._task_store = task_store
        self._bus = message_bus
        self._llm = llm_client
        self._persist_lock = threading.Lock()
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._running_jobs: dict[str, RunningSubagentJob] = {}
        self._worker_loop: asyncio.AbstractEventLoop | None = None
        self._worker_thread: threading.Thread | None = None
        self._worker_ready = threading.Event()
        self._worker_stop = threading.Event()
        self._worker_lock = threading.Lock()
        self._announced_job_ids: set[str] = set()
        self.max_concurrency = 2

    def create_task(self, kind: str, payload: dict, *, parent_trace_id: str | None = None) -> Any:
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
        return self._task_store.list_recent(limit)

    def _persist(self, task) -> None:
        try:
            self._append_record({
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
            })
        except Exception:
            logger.exception("failed persisting subagent task")

    def _append_record(self, record: dict[str, Any]) -> None:
        """以线程安全方式追加一条子代理运行记录。"""

        self._task_store.append(record)

    def _trace(self, job_id: str, phase: str, payload: dict[str, Any]) -> None:
        """记录后台子代理状态，追踪失败不得影响任务本身。"""

        try:
            self._append_record({
                "type": "spawn_trace",
                "job_id": job_id,
                "phase": phase,
                "created_at": datetime.now(timezone.utc).isoformat(),
                **payload,
            })
        except Exception:
            logger.exception("记录子代理状态失败: job_id=%s phase=%s", job_id, phase)

    def _ensure_worker_loop(self) -> asyncio.AbstractEventLoop:
        """按需启动持久事件循环，防止后台任务随临时循环一起被取消。"""

        with self._worker_lock:
            if (
                self._worker_loop is not None
                and not self._worker_loop.is_closed()
                and self._worker_thread is not None
                and self._worker_thread.is_alive()
            ):
                return self._worker_loop

            self._worker_ready.clear()
            self._worker_stop.clear()

            def run_loop() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._worker_loop = loop
                self._worker_ready.set()
                try:
                    # 短周期驱动可兼容跨线程唤醒管道失效的运行环境。
                    while not self._worker_stop.is_set():
                        loop.run_until_complete(asyncio.sleep(0.05))
                finally:
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                    if pending:
                        loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                    loop.close()

            self._worker_thread = threading.Thread(
                target=run_loop,
                name="subagent-worker",
                daemon=True,
            )
            self._worker_thread.start()

        if not self._worker_ready.wait(timeout=5):
            raise RuntimeError("子代理事件循环启动超时")
        if self._worker_loop is None:
            raise RuntimeError("子代理事件循环启动失败")
        return self._worker_loop

    def run_spawn_threadsafe(
        self,
        *,
        run_in_background: bool,
        task: str,
        label: str | None,
        profile: str,
        origin_channel: str,
        origin_chat_id: str,
        origin_session_id: str,
        decision: SpawnDecision | None = None,
    ) -> str:
        """从同步工具线程安全地提交子代理任务。"""

        loop = self._ensure_worker_loop()
        if run_in_background:
            coroutine = self.spawn(
                task=task,
                label=label,
                profile=profile,
                origin_channel=origin_channel,
                origin_chat_id=origin_chat_id,
                origin_session_id=origin_session_id,
                decision=decision,
            )
        else:
            coroutine = self.spawn_sync(task=task, label=label, profile=profile)
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        return future.result(timeout=300)

    def shutdown(self, timeout: float = 5.0) -> None:
        """停止子代理工作循环并取消尚未完成的任务。"""

        thread = self._worker_thread
        self._worker_stop.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._worker_loop = None
        self._worker_thread = None


    # ── 子代理创建 ──

    async def spawn(
        self,
        *,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "default",
        origin_session_id: str = "",
        profile: str = PROFILE_RESEARCH,
        retry_count: int = 0,
        decision: SpawnDecision | None = None,
    ) -> str:
        """创建后台子代理任务并立即返回确认。"""
        if len(self._running_tasks) >= self.max_concurrency:
            return f"已到达最大并行数 ({self.max_concurrency})，请稍后再试。"

        job_id = uuid4().hex[:12]
        display_label = label or task[:40]

        # 在创建异步任务前先落盘，便于进程异常时定位未完成任务。
        self._trace(job_id, "started", {
            "label": display_label,
            "origin_channel": origin_channel,
            "origin_chat_id": origin_chat_id,
            "profile": profile,
        })

        # 后台任务必须绑定到管理器的持久事件循环。
        bg_task = asyncio.create_task(
            self._run_subagent(
                job_id=job_id,
                task=task,
                label=display_label,
                origin_channel=origin_channel,
                origin_chat_id=origin_chat_id,
                origin_session_id=origin_session_id or origin_chat_id,
                profile=profile,
                retry_count=retry_count,
            ),
            name=f"spawn:{job_id}",
        )

        # 注册运行状态，供并发限制和运行中查询使用。
        self._running_tasks[job_id] = bg_task
        self._running_jobs[job_id] = RunningSubagentJob(
            job_id=job_id,
            label=display_label,
            task=task,
            profile=profile,
            origin_channel=origin_channel,
            origin_chat_id=origin_chat_id,
            origin_session_id=origin_session_id or origin_chat_id,
            task_dir=str(self._task_store.path.parent),
            retry_count=retry_count,
        )

        # 立即返回确认，不等待子代理执行完成。
        return (
            f"已创建后台任务「{display_label}」（job_id={job_id}）。"
            "不要等待其完成；请直接向用户说明你已开始处理，完成后会继续回复。"
        )

    # ── 同步子代理 ──

    async def spawn_sync(
        self,
        *,
        task: str,
        label: str | None = None,
        profile: str = PROFILE_RESEARCH,
    ) -> str:
        """创建子代理并等待执行完成。"""
        spec = build_spawn_spec(profile=profile, max_iterations=_SPAWN_MAX_ITERATIONS)
        agent = spec.build(runtime=self)
        return await agent.run(task)

    # ── 后台执行 ──

    async def _run_subagent(
        self,
        *,
        job_id: str,
        task: str,
        label: str,
        origin_channel: str,
        origin_chat_id: str,
        origin_session_id: str,
        profile: str,
        retry_count: int = 0,
    ) -> None:
        """构建并运行子代理，然后向原会话发布完成通知。"""
        try:
            # 每次任务独立构建执行器，避免不同子代理共享对话状态。
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

            # 执行结果先落盘，再向消息总线发布通知。
            result = await runner.run(job_spec)

            self._trace(job_id, result.status, {
                "label": label,
                "exit_reason": result.exit_reason,
                "result": result.result_summary[:1000],
            })

            await self._announce_result(
                job_id=job_id,
                label=label,
                task=task,
                origin_channel=origin_channel,
                origin_chat_id=origin_chat_id,
                origin_session_id=origin_session_id,
                status=result.status,
                exit_reason=result.exit_reason,
                result=result.result_summary,
                profile=profile,
                retry_count=retry_count,
            )
        except Exception as exc:
            logger.exception("[spawn] _run_subagent failed job_id=%s", job_id)
            self._trace(job_id, "error", {
                "label": label,
                "error": str(exc),
            })
            await self._announce_result(
                job_id=job_id, label=label, task=task,
                origin_channel=origin_channel, origin_chat_id=origin_chat_id,
                origin_session_id=origin_session_id,
                status="error", exit_reason="error",
                result=f"error: {exc}", profile=profile, retry_count=retry_count,
            )
        finally:
            self._running_tasks.pop(job_id, None)
            self._running_jobs.pop(job_id, None)

    # ── 消息总线完成通知 ──

    async def _announce_result(
        self,
        *,
        job_id: str,
        label: str,
        task: str,
        origin_channel: str,
        origin_chat_id: str,
        origin_session_id: str,
        status: str,
        exit_reason: str,
        result: str,
        profile: str,
        retry_count: int = 0,
        decision: SpawnDecision | None = None,
    ) -> None:
        """把子代理完成事件作为原会话的新入站消息发布。"""
        if self._bus is None:
            logger.warning("[spawn] no message bus, cannot announce completion")
            return
        with self._persist_lock:
            if job_id in self._announced_job_ids:
                logger.info("[spawn] duplicate completion ignored: job_id=%s", job_id)
                return
            self._announced_job_ids.add(job_id)

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

        # 完成事件重新进入 AgentLoop，由主代理组织最终用户回复。
        from infra.bus.types import InboundMessage
        msg = InboundMessage(
            channel=origin_channel,
            session_id=origin_session_id or origin_chat_id,
            text=json.dumps({
                "type": "spawn_completion",
                "job_id": job_id,
                "label": label,
                "status": status,
                "result": result[:_COMPLETION_RESULT_MAX_CHARS],
            }, ensure_ascii=False),
            chat_id=origin_chat_id,
            metadata={
                "background_completion": True,
            },
        )
        self._bus.publish_inbound(msg)
        logger.info("[spawn] completion announced: job_id=%s status=%s", job_id, status)

    @property
    def running_count(self) -> int:
        return len(self._running_tasks)

    @property
    def llm_client(self) -> Any:
        """向子代理构建器公开当前模型客户端。"""

        return self._llm

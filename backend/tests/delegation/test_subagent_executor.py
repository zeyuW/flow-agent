import asyncio

import pytest

from application.delegation.app.executor import SubagentExecutor


class FakeAgent:
    last_exit_reason = "completed"
    last_steps = 2

    async def run(self, task: str) -> str:
        assert "目标：整理资料" in task
        assert "上下文：只看本地文件" in task
        return "资料已整理"


class FakeSpec:
    def build(self, runtime):
        assert runtime == "runtime"
        return FakeAgent()


def test_executor_returns_structured_success_result():
    executor = SubagentExecutor(
        runtime="runtime",
        spec_builder=lambda **kwargs: FakeSpec(),
    )

    result = asyncio.run(
        executor.execute(
            task_id="task-1",
            description="整理资料",
            profile="research",
            context="只看本地文件",
        )
    )

    assert result.to_dict() == {
        "task_id": "task-1",
        "status": "completed",
        "summary": "资料已整理",
        "error": None,
        "steps": 2,
    }


def test_executor_converts_agent_failure_to_result():
    class FailedAgent(FakeAgent):
        last_exit_reason = "max_iterations"

        async def run(self, task: str) -> str:
            return "达到步数上限"

    executor = SubagentExecutor(
        runtime="runtime",
        spec_builder=lambda **kwargs: type(
            "Spec", (), {"build": lambda self, runtime: FailedAgent()}
        )(),
    )

    result = asyncio.run(
        executor.execute(task_id="task-2", description="继续执行")
    )

    assert result.status == "failed"
    assert result.summary == "达到步数上限"
    assert result.error == "max_iterations"


def test_executor_converts_exception_to_failed_result():
    class BrokenAgent(FakeAgent):
        async def run(self, task: str) -> str:
            raise RuntimeError("模型不可用")

    executor = SubagentExecutor(
        runtime="runtime",
        spec_builder=lambda **kwargs: type(
            "Spec", (), {"build": lambda self, runtime: BrokenAgent()}
        )(),
    )

    result = asyncio.run(
        executor.execute(task_id="task-3", description="执行任务")
    )

    assert result.status == "failed"
    assert result.error == "模型不可用"


def test_executor_converts_timeout_to_timed_out_result():
    class SlowAgent(FakeAgent):
        async def run(self, task: str) -> str:
            await asyncio.sleep(1.05)
            return task

    executor = SubagentExecutor(
        runtime="runtime",
        spec_builder=lambda **kwargs: type(
            "Spec", (), {"build": lambda self, runtime: SlowAgent()}
        )(),
    )

    result = asyncio.run(
        executor.execute(task_id="task-4", description="执行任务", timeout=1)
    )

    assert result.status == "timed_out"
    assert result.error == "subagent_timeout"

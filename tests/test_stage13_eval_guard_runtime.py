from pathlib import Path

from flow_agent.eval.baseline import BaselineStore
from flow_agent.eval.runner import EvalRunner
from flow_agent.eval.scenarios import EvalScenario
from flow_agent.guard.guards import ToolGuard
from flow_agent.runtime.fallback import with_fallback
from flow_agent.runtime.retry import RetryPolicy, retry_call
from flow_agent.tools.base import ToolResult
from flow_agent.tools.registry import ToolRegistry


class EchoTool:
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "echo"

    @property
    def input_schema(self) -> dict[str, object]:
        return {"type": "object", "properties": {"text": {"type": "string"}}}

    def run(self, tool_input: dict[str, str]) -> ToolResult:
        return ToolResult(ok=True, content=tool_input.get("text", ""))


def test_retry_and_fallback():
    state = {"n": 0}

    def flaky() -> int:
        state["n"] += 1
        if state["n"] < 2:
            raise RuntimeError("x")
        return 42

    got = retry_call(flaky, policy=RetryPolicy(max_attempts=2, delay_seconds=0))
    assert got == 42

    val = with_fallback(lambda: (_ for _ in ()).throw(ValueError("e")), lambda exc: 7)
    assert val == 7


def test_tool_guard_blocks_blacklist():
    registry = ToolRegistry()
    registry.register(EchoTool())
    registry.set_guard(ToolGuard(blacklist={"echo"}))
    result = registry.execute("echo", {"text": "hi"})
    assert result.ok is False
    assert "Guard blocked tool" in result.content


def test_eval_runner_with_baseline(tmp_path: Path):
    baseline = BaselineStore(path=tmp_path / "baseline.json")
    runner = EvalRunner(
        scenarios=[EvalScenario(name="s1", run=lambda: {"status": "ok", "branch": "a"})],
        baseline_store=baseline,
    )
    first = runner.run_all(update_baseline=True)
    assert first.total == 1
    second = runner.run_all(update_baseline=False)
    assert second.failed == 0


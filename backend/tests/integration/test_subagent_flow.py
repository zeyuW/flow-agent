from application.capabilities.llm.client import LLMResult, LLMToolCall
from application.capabilities.tools.registry import ToolRegistry
from application.delegation.app.manager import SubagentManager
from application.delegation.app.models import SubagentResult
from application.delegation.app.task_tool import TaskTool
from application.delegation.infra.store import JsonlTaskStore
from application.passive.app.phase import TurnFlow
from application.passive.app.reasoning import PassiveReasoner
from infra.bus.event import EventBus


class _LeadAgent:
    def __init__(self) -> None:
        self.calls = 0

    def generate_from_messages(self, messages, *, tools=None):
        del messages, tools
        self.calls += 1
        if self.calls == 1:
            return LLMResult(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="task-call",
                        name="task",
                        arguments_json='{"description":"检查项目结构"}',
                        arguments={"description": "检查项目结构"},
                    )
                ],
            )
        return LLMResult(content="项目结构检查完成，主 Agent 已汇总结果。")


class _Executor:
    async def execute(self, **kwargs):
        return SubagentResult(
            task_id=kwargs["task_id"],
            status="completed",
            summary="发现 3 个主要模块",
            steps=2,
        )


class _EventSpy:
    def __init__(self) -> None:
        self.events = []

    def on_event(self, event) -> None:
        self.events.append(event)


def test_lead_agent_task_subagent_result_and_final_summary(tmp_path):
    manager = SubagentManager(task_store=JsonlTaskStore(tmp_path / "tasks.jsonl"))
    manager._executor = _Executor()
    registry = ToolRegistry()
    registry.register(TaskTool(manager))
    lead = _LeadAgent()
    flow = TurnFlow(
        user_input="检查项目结构",
        session_id="cli:1",
        channel="cli",
        trace_id="trace-1",
        messages=[{"role": "user", "content": "检查项目结构"}],
        tools=[{"type": "function", "function": {"name": "task"}}],
    )

    try:
        result = PassiveReasoner(
            agent=lead,
            tool_registry=registry,
            max_tool_steps=2,
        ).run_sync(flow)
    finally:
        manager.shutdown()

    assert result.final_output == "项目结构检查完成，主 Agent 已汇总结果。"
    assert lead.calls == 2


def test_task_subagent_publishes_lifecycle_events_under_parent_trace(tmp_path):
    event_bus = EventBus()
    spy = _EventSpy()
    event_bus.subscribe(spy)
    manager = SubagentManager(
        task_store=JsonlTaskStore(tmp_path / "tasks.jsonl"),
        event_bus=event_bus,
    )
    manager._executor = _Executor()

    try:
        result = manager.run_task_threadsafe(
            task_id="task-1",
            description="检查项目结构",
            run_id="trace-parent",
        )
    finally:
        manager.shutdown()

    assert result.status == "completed"
    assert [event.event_type for event in spy.events] == [
        "subagent_started",
        "subagent_completed",
    ]
    assert {event.trace_id for event in spy.events} == {"trace-parent"}
    assert all(event.payload["job_id"] == "task-1" for event in spy.events)

import json

from application.delegation.app.models import SubagentResult
from application.delegation.app.task_tool import TaskTool


class FakeManager:
    def __init__(self, result: SubagentResult) -> None:
        self.result = result
        self.arguments = None

    def run_task_threadsafe(self, **kwargs):
        self.arguments = kwargs
        return self.result


def test_task_tool_returns_subagent_result_to_lead_agent():
    manager = FakeManager(
        SubagentResult(
            task_id="task-1",
            status="completed",
            summary="已完成调研",
            steps=3,
        )
    )
    tool = TaskTool(manager)

    result = tool.run({
        "description": "调研 MCP 协议",
        "profile": "research",
        "context": "只关注官方资料",
        "max_turns": 8,
        "timeout": 120,
    })

    assert result.ok is True
    assert json.loads(result.content)["summary"] == "已完成调研"
    assert manager.arguments == {
        "task_id": manager.arguments["task_id"],
        "description": "调研 MCP 协议",
        "profile": "research",
        "context": "只关注官方资料",
        "max_turns": 8,
        "timeout": 120,
        "run_id": "default",
    }


def test_task_tool_returns_failed_result_without_raising():
    tool = TaskTool(
        FakeManager(
            SubagentResult(
                task_id="task-2",
                status="failed",
                error="模型不可用",
            )
        )
    )

    result = tool.run({"description": "执行任务"})

    assert result.ok is False
    assert json.loads(result.content)["error"] == "模型不可用"


def test_task_tool_exposes_structured_input_schema():
    schema = TaskTool(None).input_schema

    assert schema["required"] == ["description"]
    assert set(schema["properties"]) == {
        "description",
        "profile",
        "context",
        "max_turns",
        "timeout",
    }
    assert schema["properties"]["max_turns"]["default"] == 10
    assert schema["properties"]["timeout"]["default"] == 300

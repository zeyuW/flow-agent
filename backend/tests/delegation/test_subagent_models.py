from application.delegation.app.models import SubagentResult


def test_subagent_result_serializes_success():
    result = SubagentResult(
        task_id="task-1",
        status="completed",
        summary="已完成调研",
        steps=3,
    )

    assert result.to_dict() == {
        "task_id": "task-1",
        "status": "completed",
        "summary": "已完成调研",
        "error": None,
        "steps": 3,
    }


def test_subagent_result_rejects_unknown_status():
    try:
        SubagentResult(task_id="task-1", status="unknown", summary="")
    except ValueError as exc:
        assert "不支持的 Subagent 状态" in str(exc)
    else:
        raise AssertionError("expected ValueError")

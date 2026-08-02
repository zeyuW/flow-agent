"""recall_memory 工具输入边界测试。"""

import json

import pytest

from modules.memory.memory_engine import MemoryQueryResult
from modules.memory.application.recall_memory import RecallMemoryTool, RecallMemoryToolAdapter


class RecordingMemoryEngine:
    """记录查询参数，验证非法类型不会进入检索层。"""

    def __init__(self) -> None:
        self.queries = []

    def query(self, query):
        self.queries.append(query)
        return MemoryQueryResult(query=query, hits=[], total_active=0)


def test_integral_float_max_items_is_normalized_to_int():
    engine = RecordingMemoryEngine()
    tool = RecallMemoryTool(engine=engine)

    result = json.loads(tool(json.dumps({"query": "偏好", "max_items": 8.0})))

    assert result["found"] == 0
    assert engine.queries[0].max_items == 8
    assert type(engine.queries[0].max_items) is int


@pytest.mark.parametrize(
    "max_items",
    [True, "8", 1.5, float("nan"), float("inf"), 0, 51],
)
def test_invalid_max_items_returns_tool_error(max_items):
    engine = RecordingMemoryEngine()
    adapter = RecallMemoryToolAdapter(RecallMemoryTool(engine=engine))

    result = adapter.run({"query": "偏好", "max_items": max_items})

    assert result.ok is False
    assert json.loads(result.content)["error"] == (
        "max_items must be an integer between 1 and 50"
    )
    assert engine.queries == []


def test_non_object_payload_returns_tool_error():
    engine = RecordingMemoryEngine()
    tool = RecallMemoryTool(engine=engine)

    result = json.loads(tool("[]"))

    assert result == {"error": "payload must be an object"}
    assert engine.queries == []

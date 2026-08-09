"""子代理工具与持久事件循环的回归测试。"""

import asyncio
import json
import threading
import time

from infra.bus.message import MessageBus
from application.delegation.app.manager import SubagentManager
from application.delegation.app.spawn import SpawnTool
from application.delegation.infra.store import JsonlTaskStore


class AllowPolicy:
    """测试中固定允许创建子代理。"""

    def decide(self, **kwargs):
        del kwargs
        return type("Decision", (), {"action": "spawn_subagent", "reason": "ok"})()


class ThreadsafeManager:
    """记录 SpawnTool 传入的会话上下文。"""

    def __init__(self) -> None:
        self.arguments = None

    def run_spawn_threadsafe(self, **kwargs):
        self.arguments = kwargs
        return "created"


class ImmediateLLM:
    """不调用工具并立即结束子代理任务的模型替身。"""

    def generate(self, messages, tools=None):
        del messages, tools
        return type("Response", (), {"content": "调研完成", "tool_calls": []})()


def test_spawn_tool_passes_telegram_context_inside_running_loop():
    manager = ThreadsafeManager()
    tool = SpawnTool(manager=manager, policy=AllowPolicy())

    result = tool.run({
        "task": "整理资料",
        "__channel": "telegram",
        "__chat_id": "12345",
    })

    assert result.ok is True
    assert result.content == "created"
    assert manager.arguments["origin_channel"] == "telegram"
    assert manager.arguments["origin_chat_id"] == "12345"
    assert manager.arguments["origin_session_id"] == "12345"


def test_background_spawn_survives_submission_return(tmp_path, monkeypatch):
    manager = SubagentManager(task_store=JsonlTaskStore(tmp_path / "tasks.jsonl"), llm_client=object())
    completed = threading.Event()

    async def fake_run_subagent(**kwargs):
        manager._trace(kwargs["job_id"], "completed", {"label": kwargs["label"]})
        completed.set()
        manager._running_tasks.pop(kwargs["job_id"], None)
        manager._running_jobs.pop(kwargs["job_id"], None)

    monkeypatch.setattr(manager, "_run_subagent", fake_run_subagent)
    try:
        confirmation = manager.run_spawn_threadsafe(
            run_in_background=True,
            task="后台测试",
            label="真机探针",
            profile="research",
            origin_channel="telegram",
            origin_chat_id="12345",
            origin_session_id="12345",
        )

        assert "已创建后台任务" in confirmation
        assert completed.wait(timeout=2)
        records = [
            json.loads(line)
            for line in (tmp_path / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert [record["phase"] for record in records] == ["started", "completed"]
        assert records[0]["origin_channel"] == "telegram"
        assert manager.llm_client is not None
    finally:
        manager.shutdown()


def test_background_spawn_notifies_original_telegram_chat(tmp_path):
    bus = MessageBus()
    manager = SubagentManager(
        task_store=JsonlTaskStore(tmp_path / "tasks.jsonl"),
        message_bus=bus,
        llm_client=ImmediateLLM(),
    )
    try:
        manager.run_spawn_threadsafe(
            run_in_background=True,
            task="完成调研",
            label="调研任务",
            profile="research",
            origin_channel="telegram",
            origin_chat_id="8706327858",
            origin_session_id="8706327858",
        )

        deadline = time.monotonic() + 2
        message = None
        while time.monotonic() < deadline and message is None:
            message = bus.consume_inbound()
            if message is None:
                time.sleep(0.01)

        assert message is not None
        assert message.channel == "telegram"
        assert message.session_id == "8706327858"
        assert message.chat_id == "8706327858"
        payload = json.loads(message.text)
        assert payload["type"] == "spawn_completion"
        assert payload["status"] == "completed"
        assert payload["result"] == "调研完成"
    finally:
        manager.shutdown()


def test_background_completion_keeps_long_result_and_chat_metadata(tmp_path):
    bus = MessageBus()
    manager = SubagentManager(
        task_store=JsonlTaskStore(tmp_path / "tasks.jsonl"),
        message_bus=bus,
        llm_client=ImmediateLLM(),
    )
    long_result = "结果" * 2000

    asyncio.run(manager._announce_result(
        job_id="job-long",
        label="长结果",
        task="整理",
        origin_channel="telegram",
        origin_chat_id="8706327858",
        origin_session_id="8706327858",
        status="completed",
        exit_reason="completed",
        result=long_result,
        profile="research",
    ))

    message = bus.consume_inbound()
    assert message is not None
    assert message.chat_id == "8706327858"
    assert json.loads(message.text)["result"] == long_result

"""主动数据源精确确认测试。"""

import asyncio

from application.proactive.domain.models import DataItem, JudgeResult
from application.proactive.app.resolve import resolve_decision
from application.proactive.infra.gate import ProactiveStateStore


class _Source:
    def __init__(self, key, server):
        self.source_key = key
        self.spec = type("Spec", (), {"server": server, "ack_tool": "ack"})()


def test_ack_effects_group_cited_events_by_registered_source():
    """不同来源的引用事件必须分别确认。"""

    calls = []

    class Pool:
        async def call(self, server, tool, arguments):
            calls.append((server, tool, arguments))

    result = resolve_decision(
        JudgeResult(decision="reply", message="消息", cited_item_ids=["a", "b"]),
        state_store=ProactiveStateStore(),
        mcp_pool=Pool(),
        sources=[_Source("plugin:first", "first"), _Source("plugin:second", "second")],
        items=[
            DataItem(source="first", source_key="plugin:first", item_id="a", title="A"),
            DataItem(source="second", source_key="plugin:second", item_id="b", title="B"),
        ],
    )

    async def scenario():
        for effect in result.side_effects:
            value = effect()
            if asyncio.iscoroutine(value):
                await value

    asyncio.run(scenario())

    assert calls == [
        ("first", "ack", {"event_ids": ["a"]}),
        ("second", "ack", {"event_ids": ["b"]}),
    ]


def test_ambiguous_item_id_does_not_create_ack_effect():
    """跨来源重复的裸事件 ID 不得被猜测性确认。"""

    result = resolve_decision(
        JudgeResult(decision="reply", message="消息", cited_item_ids=["same"]),
        state_store=ProactiveStateStore(),
        mcp_pool=object(),
        sources=[_Source("plugin:first", "first"), _Source("plugin:second", "second")],
        items=[
            DataItem(source="first", source_key="plugin:first", item_id="same", title="A"),
            DataItem(source="second", source_key="plugin:second", item_id="same", title="B"),
        ],
    )

    assert len(result.side_effects) == 1


def test_delivery_failure_does_not_run_ack_effect():
    """渠道未确认送达时，任何投递后确认副作用都不能执行。"""

    from application.proactive.app.deliver import deliver_message
    from application.proactive.domain.models import ResolveResult

    called = []

    class FailedPort:
        async def send_and_wait(self, dispatch, timeout=30.0):
            del dispatch, timeout
            return type("Receipt", (), {"delivered": False, "error": "failed"})()

    result = asyncio.run(
        deliver_message(
            ResolveResult(
                decision="send",
                message="消息",
                side_effects=[lambda: called.append("ack")],
            ),
            chat_id="chat",
            outbound_port=FailedPort(),
        )
    )

    assert result.sent is False
    assert called == []

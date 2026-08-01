import asyncio

from flow_agent.channels.models import ChannelDeliveryResult
from flow_agent.messaging.message_bus import MessageBus, OutboundDispatch
from flow_agent.messaging.outbox import SQLiteOutboxStore
from flow_agent.proactive.deliver import deliver_message
from flow_agent.proactive.models import ResolveResult
from flow_agent.subagent.manager import SubagentManager


def test_proactive_delivery_uses_stable_delivery_key():
    class Port:
        def __init__(self):
            self.dispatch = None

        async def send_and_wait(self, dispatch, timeout=30.0):
            self.dispatch = dispatch
            return type("Receipt", (), {"delivered": True, "error": ""})()

    port = Port()
    result = asyncio.run(
        deliver_message(
            ResolveResult(
                decision="send",
                message="主动消息",
                delivery_key="stable-delivery",
            ),
            chat_id="chat-1",
            outbound_port=port,
        )
    )

    assert result.sent is True
    assert port.dispatch.delivery_id == "stable-delivery"


def test_outbox_skips_already_delivered_delivery_id(tmp_path):
    store = SQLiteOutboxStore(tmp_path / "outbox.db")
    store.prepare(
        delivery_id="stable",
        channel="cli",
        session_id="chat-1",
        chat_id="chat-1",
        text="已送达",
        metadata={},
    )
    store.mark_delivered("stable")
    bus = MessageBus(outbox_store=store)

    handle = bus.outbound_port.send(
        OutboundDispatch(
            delivery_id="stable",
            channel="cli",
            session_id="chat-1",
            text="已送达",
        )
    )

    assert handle.receipt() is not None
    assert handle.receipt().delivered is True
    assert bus.outbound.consume_one() is None


def test_subagent_completion_is_idempotent(tmp_path):
    from flow_agent.messaging.message_bus import MessageBus

    bus = MessageBus()
    manager = SubagentManager(
        tasks_path=tmp_path / "tasks.jsonl",
        message_bus=bus,
    )

    async def scenario():
        kwargs = {
            "job_id": "job-1",
            "label": "任务",
            "task": "执行",
            "origin_channel": "cli",
            "origin_chat_id": "chat-1",
            "origin_session_id": "chat-1",
            "status": "completed",
            "exit_reason": "completed",
            "result": "完成",
            "profile": "research",
        }
        await manager._announce_result(**kwargs)
        await manager._announce_result(**kwargs)

    asyncio.run(scenario())

    assert bus.consume_inbound() is not None
    assert bus.consume_inbound() is None


def test_agent_loop_stop_cancels_hanging_task():
    from flow_agent.core.agent_loop import AgentLoop

    class Bus:
        pass

    class Pipeline:
        def process(self, inbound):
            del inbound
            asyncio.sleep(3600)

    loop = AgentLoop(Bus(), Pipeline())

    async def scenario():
        task = asyncio.create_task(asyncio.sleep(3600))
        loop._active_tasks.add(task)
        await loop.stop(timeout=0.01)

    asyncio.run(scenario())

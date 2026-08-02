import asyncio

from interfaces.channels.models import ChannelDeliveryResult
from modules.delivery.infra.delivery_bus import DeliveryBus, OutboundDispatch
from modules.delivery.infra.outbox import SQLiteOutboxStore
from modules.proactive.application.deliver import deliver_message
from modules.proactive.domain.models import ResolveResult
from modules.delegation.application.manager import SubagentManager
from infra.persistence.sqlite import SQLiteDatabase


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
    bus = DeliveryBus(outbox_store=store)

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


def test_outbox_uses_shared_sqlite_infrastructure(tmp_path):
    store = SQLiteOutboxStore(tmp_path / "outbox.db")

    assert isinstance(store.database, SQLiteDatabase)

    store.close()


def test_subagent_completion_is_idempotent(tmp_path):
    from modules.delivery.infra.delivery_bus import DeliveryBus

    bus = DeliveryBus()
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
    from modules.conversation.application.agent_loop import AgentLoop

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

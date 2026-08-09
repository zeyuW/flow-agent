"""统一 MessageBus 的收发与确认契约。"""

import asyncio


def test_message_bus_sends_outbound_message_to_channel_queue():
    """业务发送端口提交的消息必须进入总线出站队列。"""

    from infra.bus.types import SendMessage
    from infra.bus.message import MessageBus

    bus = MessageBus()
    result = bus.send(
        SendMessage(
            channel="telegram",
            conversation_id="telegram:42",
            recipient_id="42",
            text="回复",
        )
    )

    message = bus.outbound.consume_one()
    assert message is not None
    assert message is not None
    assert result.accepted is True
    assert result.message_id
    assert message.channel == "telegram"
    assert message.chat_id == "42"
    assert message.text == "回复"


def test_message_bus_consumer_acknowledges_inbound_message():
    """消费端确认后，消息不应继续留在待确认集合中。"""

    from infra.bus.types import InboundMessage
    from infra.bus.message import MessageBus

    async def scenario() -> None:
        bus = MessageBus()
        bus.publish_inbound(
            InboundMessage(
                channel="telegram",
                session_id="telegram:42",
                text="输入",
                sender="42",
            )
        )

        received = await bus.receive(poll_interval_ms=1)
        assert received.conversation_id == "telegram:42"
        assert received.text == "输入"
        assert received.message_id in bus._inbound_pending

        await bus.ack(received.message_id)

        assert received.message_id not in bus._inbound_pending

    asyncio.run(scenario())


def test_message_bus_nack_requeues_unhandled_message():
    """业务处理失败时，技术层 nack 必须把消息重新放回入站队列。"""

    from infra.bus.types import InboundMessage
    from infra.bus.message import MessageBus

    async def scenario() -> None:
        bus = MessageBus()
        bus.publish_inbound(
            InboundMessage(channel="telegram", session_id="42", text="重试")
        )
        received = await bus.receive(poll_interval_ms=1)
        await bus.nack(received.message_id, retry=True)
        retried = await bus.receive(poll_interval_ms=1)
        assert retried.text == "重试"

    asyncio.run(scenario())

from __future__ import annotations

from infra.bus.message import MessageBus
from infra.bus.types import SendMessage


def test_send_message_recipient_becomes_outbound_chat_id():
    bus = MessageBus()

    result = bus.send(
        SendMessage(
            channel="fake",
            conversation_id="fake:chat-1",
            recipient_id="chat-1",
            text="回复",
        )
    )

    outbound = bus.outbound.consume_one()
    assert result.accepted is True
    assert outbound is not None
    assert outbound.channel == "fake"
    assert outbound.session_id == "fake:chat-1"
    assert outbound.chat_id == "chat-1"
    assert outbound.text == "回复"

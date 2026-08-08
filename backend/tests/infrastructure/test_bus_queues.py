from dataclasses import dataclass

from infra.bus.queues import InboundQueue, OutboundQueue


@dataclass(frozen=True)
class _Message:
    channel: str
    text: str


def test_inbound_queue_preserves_fifo_order():
    queue = InboundQueue()
    first = _Message(channel="web", text="first")
    second = _Message(channel="web", text="second")

    queue.publish(first)
    queue.publish(second)

    assert queue.size == 2
    assert queue.consume_one() is first
    assert queue.consume_one() is second
    assert queue.consume_one() is None


def test_outbound_queue_dispatches_to_channel_subscriber():
    queue = OutboundQueue()
    received: list[_Message] = []
    queue.subscribe("web", received.append)

    message = _Message(channel="web", text="reply")
    queue.dispatch(message)

    assert received == [message]
    assert queue.consume_one() is message

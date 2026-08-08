"""消息传输契约的架构约束。"""

import inspect


def test_message_ports_expose_narrow_send_and_consume_contracts():
    """发送和消费端口必须分离，业务方不应依赖完整总线。"""

    from infra.bus.types import MessageConsumer
    from infra.bus.types import MessageSender, SendMessage

    assert inspect.isabstract(MessageSender) is False
    assert inspect.isabstract(MessageConsumer) is False
    assert {"send"} <= set(MessageSender.__dict__)
    assert {"receive", "ack", "nack"} <= set(MessageConsumer.__dict__)
    message = SendMessage(
        channel="telegram",
        recipient_id="42",
        text="测试",
    )
    assert message.channel == "telegram"
    assert message.recipient_id == "42"


def test_message_bus_implements_the_two_transport_roles():
    """MessageBus 应实现收发端口，但业务只注入其中一个角色。"""

    from infra.bus.types import MessageConsumer
    from infra.bus.types import MessageSender
    from infra.bus.message import MessageBus

    bus = MessageBus()
    assert isinstance(bus, MessageSender)
    assert isinstance(bus, MessageConsumer)

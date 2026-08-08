from infra.bus import MessageBus


def test_infrastructure_message_bus_routes_inbound_and_outbound_messages():
    bus = MessageBus()
    inbound = object()
    outbound = type("Message", (), {"channel": "web"})()

    bus.publish_inbound(inbound)
    bus.publish_outbound(outbound)
    bus.dispatch_outbound(outbound)

    assert bus.consume_inbound() is inbound
    assert bus.outbound.consume_one() is outbound

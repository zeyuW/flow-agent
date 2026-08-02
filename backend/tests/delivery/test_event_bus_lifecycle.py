import asyncio

from infra.messagebus.event_bus import Event, EventBus


def test_typed_event_bus_emit_is_ordered_and_replaceable():
    bus = EventBus()
    seen = []

    def first(event):
        seen.append(("first", event.payload["value"]))
        event.payload["value"] += 1
        return event

    async def second(event):
        await asyncio.sleep(0)
        seen.append(("second", event.payload["value"]))

    bus.on(Event, first)
    subscription = bus.on(Event, second)

    event = asyncio.run(bus.emit(Event("test", payload={"value": 1})))

    assert seen == [("first", 1), ("second", 2)]
    assert event.payload["value"] == 2
    assert bus.handler_count == 2

    subscription.close()
    subscription.close()
    assert bus.handler_count == 1


def test_typed_event_bus_fanout_isolates_failures():
    bus = EventBus()
    seen = []

    def broken(event):
        del event
        raise RuntimeError("boom")

    async def healthy(event):
        await asyncio.sleep(0)
        seen.append(event.event_type)

    bus.on(Event, broken)
    bus.on(Event, healthy)

    asyncio.run(bus.fanout(Event("fanout")))

    assert seen == ["fanout"]


def test_typed_event_bus_on_any_receives_event():
    bus = EventBus()
    seen = []
    bus.on_any(lambda event: seen.append(event.event_type))

    asyncio.run(bus.observe(Event("any")))

    assert seen == ["any"]

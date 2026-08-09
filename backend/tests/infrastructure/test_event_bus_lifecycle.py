import asyncio

from infra.bus.event import Event, EventBus


def test_typed_event_bus_emit_is_ordered_and_replaceable():
    bus = EventBus()
    seen = []

    def first(event: Event) -> Event:
        seen.append(("first", event.payload["value"]))
        event.payload["value"] += 1
        return event

    async def second(event: Event) -> None:
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

    async def healthy(event: Event) -> None:
        await asyncio.sleep(0)
        seen.append(event.event_type)

    bus.on(Event, broken)
    bus.on(Event, healthy)

    asyncio.run(bus.fanout(Event("fanout")))

    assert seen == ["fanout"]


def test_typed_event_bus_on_any_receives_event():
    bus = EventBus()
    seen: list[str] = []

    def on_any(event: object) -> None:
        assert isinstance(event, Event)
        seen.append(event.event_type)

    bus.on_any(on_any)

    asyncio.run(bus.observe(Event("any")))

    assert seen == ["any"]

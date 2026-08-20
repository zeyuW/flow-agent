from infra.bus.event import Event, EventBus


def test_admin_api_config_defaults_to_localhost_only():
    from infra.config import AdminApiConfig

    config = AdminApiConfig()

    assert config.enabled is True
    assert config.host == "127.0.0.1"
    assert config.port == 8790


def test_admin_timeline_receives_event_bus_events():
    from application.agent.app.tracing import TraceTimeline

    event_bus = EventBus()
    timeline = TraceTimeline()
    event_bus.subscribe(timeline)
    event_bus.publish(
        Event("before_turn", trace_id="trace-1", payload={"channel": "telegram"})
    )

    assert timeline.get_trace("trace-1") is not None

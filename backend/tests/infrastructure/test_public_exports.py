def test_top_level_infrastructure_exports_are_importable():
    from infra.lifecycle import RuntimeService, RuntimeUnit, create_runtime_service
    from infra.messagebus import Event, EventBus, InboundQueue, OutboundQueue
    from infra.telemetry import TraceRecorder, configure_logging

    assert all((RuntimeService, RuntimeUnit, create_runtime_service))
    assert all((Event, EventBus, InboundQueue, OutboundQueue))
    assert all((TraceRecorder, configure_logging))

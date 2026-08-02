def test_top_level_infrastructure_exports_are_importable():
    from infra.lifecycle import RuntimeService, RuntimeUnit, create_runtime_service
    from infra.messagebus import Event, EventBus, InboundQueue, OutboundQueue
    from infra.telemetry import TraceRecorder, configure_logging

    assert all((RuntimeService, RuntimeUnit, create_runtime_service))
    assert all((Event, EventBus, InboundQueue, OutboundQueue))
    assert all((TraceRecorder, configure_logging))


def test_infrastructure_public_names_avoid_redundant_prefixes():
    from infra import InfraContainer
    from infra.telemetry import EventSnapshot, EventStore

    assert InfraContainer is not None
    assert EventSnapshot is not None
    assert EventStore is not None

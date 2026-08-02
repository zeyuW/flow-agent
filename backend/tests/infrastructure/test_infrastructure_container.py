from infra.container import InfraContainer
from infra.lifecycle import RuntimeService
from infra.bus import EventBus, MessageBus
from infra.worker import WorkerManager


def test_infrastructure_container_builds_only_shared_services():
    container = InfraContainer.create()

    assert isinstance(container.message_bus, MessageBus)
    assert isinstance(container.event_bus, EventBus)
    assert isinstance(container.runtime, RuntimeService)
    assert isinstance(container.workers, WorkerManager)

    container.close()
    container.close()

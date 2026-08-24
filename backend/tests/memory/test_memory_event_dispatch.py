from types import SimpleNamespace

from application.memory.app.memory_runtime import wire_memory_events
from infra.bus.event import EventBus, TurnCommitted
from infra.telemetry import trace_id_var


class RecordingExecutor:
    def __init__(self) -> None:
        self.jobs: list[tuple[object, tuple[object, ...]]] = []

    def submit(self, function, *args):
        self.jobs.append((function, args))
        return SimpleNamespace(add_done_callback=lambda _callback: None)


def test_turn_committed_queues_memory_processing_without_running_it_inline():
    executor = RecordingExecutor()
    calls: list[str] = []

    class PostResponseWorker:
        def on_turn_committed(self, **_kwargs):
            calls.append("post_response")

    class Runtime:
        post_response_worker = PostResponseWorker()

    class Consolidator:
        def on_turn_committed(self, _session_id):
            calls.append("consolidation")
            return SimpleNamespace(
                consolidated=True,
                history_count=0,
                pending_count=0,
            )

    event_bus = EventBus()
    wire_memory_events(
        Runtime(),
        event_bus,
        consolidator=Consolidator(),
        executor=executor,
    )

    event_bus.publish(
        TurnCommitted(
            session_id="chat-1",
            user_input="hello",
            assistant_output="hi",
        )
    )

    assert calls == []
    assert len(executor.jobs) == 1

    function, args = executor.jobs[0]
    function(*args)

    assert calls == ["post_response", "consolidation"]


def test_memory_processing_keeps_turn_trace_in_background_callback():
    executor = RecordingExecutor()
    observed: list[str | None] = []

    class PostResponseWorker:
        def on_turn_committed(self, **_kwargs):
            observed.append(trace_id_var.get())

    class Runtime:
        post_response_worker = PostResponseWorker()

    event_bus = EventBus()
    wire_memory_events(Runtime(), event_bus, executor=executor)
    event_bus.publish(TurnCommitted(trace_id="turn-123", session_id="chat-1"))

    function, args = executor.jobs[-1]
    function(*args)

    assert observed[-1] == "turn-123"

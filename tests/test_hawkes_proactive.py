"""霍克斯主动调度和事件接线测试。"""

import json
import asyncio
from datetime import datetime, timezone


from flow_agent.messaging.event_bus import Event, EventBus
from flow_agent.infra.trace import TraceRecorder
from flow_agent.proactive.gate import ProactiveStateStore
from flow_agent.proactive.data_gateway import DataGateway
from flow_agent.proactive.sources import LocalTaskSource, LocalTodoSource
from flow_agent.proactive.events import ProactiveEventBridge
from flow_agent.proactive.mcp_pool import McpClientPool
from flow_agent.proactive.models import AgentTick, GateResult
from flow_agent.proactive.proactive_loop import (
    HawkesConfig,
    HawkesProcessModel,
    ProactiveLoop,
)
from flow_agent.proactive.runtime import build_proactive_runtime


def test_hawkes_user_event_increases_intensity_and_then_decays():
    """用户互动应立即提高强度，并随时间单调衰减。"""

    config = HawkesConfig(
        base_intensity=0.1,
        excitation_alpha=0.8,
        decay_beta=0.5,
        min_interval=1.0,
        max_interval=1000.0,
    )
    model = HawkesProcessModel(config, clock=lambda: 1000.0, local_hour_fn=lambda _: 12)
    baseline = model.get_current_intensity(1000.0)
    model.add_interaction(timestamp=1000.0)

    immediate = model.get_current_intensity(1000.0)
    later = model.get_current_intensity(1600.0)

    assert immediate > baseline
    assert baseline < later < immediate


def test_hawkes_event_shortens_next_interval():
    """真实互动应缩短下一次主动检查间隔。"""

    config = HawkesConfig(
        base_intensity=0.1,
        excitation_alpha=1.0,
        decay_beta=0.1,
        time_constant=60.0,
        min_interval=1.0,
        max_interval=1000.0,
    )
    model = HawkesProcessModel(config, clock=lambda: 1000.0, local_hour_fn=lambda _: 12)
    before = model.compute_next_interval(1000.0)
    model.add_interaction(timestamp=1000.0)
    after = model.compute_next_interval(1000.0)

    assert after < before


class _FakePool:
    def __init__(self) -> None:
        self.connected = False
        self.closed = False

    async def connect_all(self) -> None:
        self.connected = True

    async def close_all(self) -> None:
        self.closed = True


class _FakePipeline:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, **kwargs) -> AgentTick:
        self.calls += 1
        tick = AgentTick(chat_id=kwargs.get("chat_id", ""))
        tick.gate_result = GateResult(passed=True, reason="ok")
        return tick


def test_loop_stop_wakes_long_scheduler_wait():
    """停止信号不应等待很长的调度超时。"""

    async def run_scenario() -> None:
        pipeline = _FakePipeline()
        pool = _FakePool()
        loop = ProactiveLoop(
            pipeline=pipeline,
            mcp_pool=pool,
            chat_id="target",
            hawkes_config=HawkesConfig(
                base_intensity=0.01,
                time_constant=60.0,
                min_interval=60.0,
                max_interval=600.0,
            ),
        )
        task = await loop.start_background()
        for _ in range(50):
            if pipeline.calls:
                break
            await asyncio.sleep(0.01)

        await asyncio.wait_for(loop.stop(), timeout=1.0)

        assert task.done()
        assert pool.connected is True
        assert pool.closed is True
        assert loop._hawkes.get_event_count(3600.0) == 0

    asyncio.run(run_scenario())


def test_stop_closes_manually_connected_resources():
    """未启动循环时，停止操作也应关闭调用方已连接的资源。"""

    async def run_scenario() -> None:
        pool = _FakePool()
        await pool.connect_all()
        loop = ProactiveLoop(
            pipeline=_FakePipeline(),
            mcp_pool=pool,
            chat_id="target",
        )

        await loop.stop()

        assert pool.closed is True

    asyncio.run(run_scenario())


def test_event_bridge_only_records_target_session():
    """无关会话和无关通道不能影响目标用户的霍克斯状态。"""

    pipeline = _FakePipeline()
    loop = ProactiveLoop(
        pipeline=pipeline,
        mcp_pool=_FakePool(),
        chat_id="target",
    )
    bridge = ProactiveEventBridge(
        loop=loop,
        target_session_id="target",
        target_channel="telegram",
    )
    timestamp = datetime.now(timezone.utc)

    bridge.on_event(
        Event(
            event_type="turn_committed",
            session_id="other",
            timestamp=timestamp,
            payload={"channel": "telegram"},
        )
    )
    bridge.on_event(
        Event(
            event_type="turn_committed",
            session_id="target",
            timestamp=timestamp,
            payload={"channel": "http"},
        )
    )
    assert loop._hawkes.get_event_count(3600.0) == 0

    bridge.on_event(
        Event(
            event_type="turn_committed",
            session_id="target",
            timestamp=timestamp,
            payload={"channel": "telegram"},
        )
    )
    assert loop._hawkes.get_event_count(3600.0) == 1


def test_disabled_runtime_does_not_create_active_resources():
    """关闭主动配置时不应创建循环或订阅事件。"""

    event_bus = EventBus()
    runtime = build_proactive_runtime(
        enabled=False,
        event_bus=event_bus,
    )

    assert runtime is None
    assert event_bus.subscriber_count == 0


def test_runtime_subscribes_target_interaction_bridge():
    """运行时工厂应把目标用户回合接入霍克斯模型。"""

    event_bus = EventBus()
    runtime = build_proactive_runtime(
        enabled=True,
        chat_id="target",
        channel="telegram",
        event_bus=event_bus,
    )
    assert runtime is not None
    assert event_bus.subscriber_count == 1

    event_bus.publish(
        Event(
            event_type="turn_committed",
            session_id="target",
            payload={"channel": "telegram"},
        )
    )

    assert runtime._hawkes.get_event_count(3600.0) == 1


def test_data_gateway_reads_workspace_local_source(tmp_path):
    """工作区本地候选文件应进入内容通道。"""

    source_file = tmp_path / "proactive_items.txt"
    source_file.write_text("需要提醒用户的事项\n", encoding="utf-8")
    gateway = DataGateway(
        McpClientPool(),
        local_source_file=source_file,
    )

    result = asyncio.run(gateway.run())

    assert [item.content for item in result.content] == ["需要提醒用户的事项"]

def test_proactive_state_and_hawkes_events_survive_restart(tmp_path):
    """主动配额、去重、漂移和互动事件应在重启后恢复。"""

    state_path = tmp_path / "proactive.db"
    first = ProactiveStateStore(state_path)
    first.mark_sent("delivery-key")
    first.mark_drift_run()
    event_time = 1990.0
    first.append_interaction_event(event_time, "user_message", 1.0)

    second = ProactiveStateStore(state_path)
    assert second.daily_count == 1
    assert second.was_delivered("delivery-key") is True
    assert second.get_drift_last_at() > 0

    model = HawkesProcessModel(
        HawkesConfig(event_retention_seconds=100.0),
        clock=lambda: 2000.0,
        local_hour_fn=lambda _: 12,
        state_store=second,
    )
    assert model.get_event_count(100.0, current_time=2000.0) == 1


def test_proactive_tick_writes_structured_trace(tmp_path):
    """主动检查应写入独立 JSONL 轨迹文件。"""

    async def run_scenario() -> None:
        recorder = TraceRecorder(tmp_path / "proactive.jsonl")
        loop = ProactiveLoop(
            pipeline=_FakePipeline(),
            mcp_pool=_FakePool(),
            chat_id="target",
            trace_recorder=recorder,
        )
        await loop._run_single_tick()

    asyncio.run(run_scenario())
    payload = json.loads((tmp_path / "proactive.jsonl").read_text(encoding="utf-8"))
    assert payload["event"] == "proactive_tick"
    assert payload["gate_reason"] == "ok"
    assert payload["sent"] is False

def test_data_gateway_reads_task_and_todo_sources(tmp_path):
    """任务和待办目录文件都应进入主动内容通道。"""

    tasks_file = tmp_path / "tasks.txt"
    todo_file = tmp_path / "todo_items.txt"
    tasks_file.write_text("整理发布说明\n", encoding="utf-8")
    todo_file.write_text("确认会议时间\n", encoding="utf-8")
    gateway = DataGateway(
        McpClientPool(),
        local_sources=[
            LocalTaskSource(tasks_file),
            LocalTodoSource(todo_file),
        ],
    )

    result = asyncio.run(gateway.run())
    assert {item.source for item in result.content} == {"local_task", "local_todo"}

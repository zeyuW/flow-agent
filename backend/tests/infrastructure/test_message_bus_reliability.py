"""可靠出站、恢复与同会话串行处理测试。"""

import asyncio
from pathlib import Path
from typing import Any, cast

from infra.bus.types import InboundMessage
from infra.bus.types import ChannelDeliveryResult, OutboundMessage
from interfaces.channels.telegram import TelegramChannel
from application.agent.app.loop import AgentLoop
from infra.bus.message import MessageBus, OutboundDispatch
from infra.persistence import SQLiteOutboxStore
from application.proactive.app.deliver import deliver_message
from application.proactive.domain.models import ResolveResult


def test_outbound_waits_for_real_channel_receipt(tmp_path: Path):
    async def scenario():
        store = SQLiteOutboxStore(tmp_path / "outbox.db")
        bus = MessageBus(outbox_store=store)
        bus._retry_delay_s = 0
        bus.subscribe_outbound("telegram", lambda message: bool(message.chat_id))
        runner = asyncio.create_task(bus.start_dispatch_task())
        try:
            receipt = await asyncio.wait_for(
                bus.outbound_port.send_and_wait(
                    OutboundDispatch(
                        channel="telegram",
                        session_id="session-1",
                        chat_id="12345",
                        text="送达测试",
                    ),
                    timeout=2,
                ),
                timeout=3,
            )
            assert receipt.delivered is True
            record = store.get(receipt.delivery_id)
            assert record is not None
            assert record.status == "delivered"
            assert record.chat_id == "12345"
        finally:
            await asyncio.wait_for(bus.stop_dispatch_task(), timeout=2)
            await asyncio.wait_for(runner, timeout=2)

    asyncio.run(scenario())


def test_failed_channel_does_not_return_success(tmp_path: Path):
    async def scenario():
        store = SQLiteOutboxStore(tmp_path / "outbox.db")
        bus = MessageBus(outbox_store=store)
        bus._retry_delay_s = 0
        calls = []

        def reject(message):
            calls.append(message.delivery_id)
            return False

        bus.subscribe_outbound("telegram", reject)
        runner = asyncio.create_task(bus.start_dispatch_task())
        try:
            receipt = await asyncio.wait_for(
                bus.outbound_port.send_and_wait(
                    OutboundDispatch(
                        channel="telegram",
                        session_id="session-1",
                        chat_id="12345",
                        text="失败测试",
                    ),
                    timeout=2,
                ),
                timeout=3,
            )
            assert receipt.delivered is False
            assert receipt.attempts == 2
            assert len(calls) == 2
            record = store.get(receipt.delivery_id)
            assert record is not None
            assert record.status == "failed"
        finally:
            await asyncio.wait_for(bus.stop_dispatch_task(), timeout=2)
            await asyncio.wait_for(runner, timeout=2)

    asyncio.run(scenario())


def test_retryable_failure_is_retried_while_agent_is_running(tmp_path: Path):
    """运行期网络失败应退避重试，成功后只保留一条已送达记录。"""

    async def scenario():
        store = SQLiteOutboxStore(tmp_path / "outbox.db")
        bus = MessageBus(outbox_store=store)
        bus._retry_delay_s = 0
        bus._runtime_retry_base_delay_s = 0.01
        bus._runtime_retry_max_delay_s = 0.02
        calls = []

        def flaky(message):
            calls.append(message.delivery_id)
            return len(calls) >= 3

        bus.subscribe_outbound("telegram", flaky)
        runner = asyncio.create_task(bus.start_dispatch_task())
        try:
            receipt = await bus.outbound_port.send_and_wait(
                OutboundDispatch(
                    channel="telegram",
                    session_id="session-1",
                    chat_id="12345",
                    text="运行期重试",
                ),
                timeout=2,
            )
            assert receipt.delivered is False
            deadline = asyncio.get_running_loop().time() + 1
            while len(calls) < 3 and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.01)
            assert len(calls) == 3
            record = store.get(calls[0])
            assert record is not None
            assert record.status == "delivered"
        finally:
            await bus.stop_dispatch_task()
            await runner

    asyncio.run(scenario())


def test_non_retryable_failure_is_not_retried(tmp_path: Path):
    """明确不可重试的渠道错误不得被运行期后台任务再次发送。"""

    async def scenario():
        store = SQLiteOutboxStore(tmp_path / "outbox.db")
        bus = MessageBus(outbox_store=store)
        bus._retry_delay_s = 0
        calls = []

        def reject(message):
            calls.append(message.delivery_id)
            return ChannelDeliveryResult(
                delivered=False,
                retryable=False,
                error="参数错误",
            )

        bus.subscribe_outbound("telegram", reject)
        runner = asyncio.create_task(bus.start_dispatch_task())
        try:
            receipt = await bus.outbound_port.send_and_wait(
                OutboundDispatch(
                    channel="telegram",
                    session_id="session-1",
                    chat_id="12345",
                    text="不可重试",
                ),
                timeout=2,
            )
            await asyncio.sleep(0.05)
            assert receipt.delivered is False
            assert len(calls) == 1
            record = store.get(calls[0])
            assert record is not None
            assert record.status == "failed"
        finally:
            await bus.stop_dispatch_task()
            await runner

    asyncio.run(scenario())


def test_pending_outbox_is_recovered_after_restart(tmp_path: Path):
    path = tmp_path / "outbox.db"
    first = MessageBus(outbox_store=SQLiteOutboxStore(path))
    handle = first.outbound_port.send(
        OutboundDispatch(
            channel="telegram",
            session_id="session-1",
            chat_id="12345",
            text="重启恢复",
        )
    )

    second_store = SQLiteOutboxStore(path)
    second = MessageBus(
        outbox_store=second_store,
        outbox_recovery_window_s=86400,
    )
    restored = second.outbound.consume_one()

    assert handle.delivery_id
    assert restored is not None
    assert restored.delivery_id == handle.delivery_id
    assert restored.text == "重启恢复"
    assert restored.chat_id == "12345"


def test_stale_outbox_is_expired_instead_of_replayed(tmp_path: Path):
    """启动恢复只允许恢复窗口内的消息，旧消息必须进入过期终态。"""

    path = tmp_path / "outbox.db"
    store = SQLiteOutboxStore(path)
    store.prepare(
        delivery_id="stale-1",
        channel="telegram",
        session_id="session-1",
        chat_id="12345",
        text="过期消息",
        metadata={},
    )
    with store.database.transaction() as connection:
        connection.execute(
            "UPDATE outbound_deliveries SET created_at = ?, updated_at = ? "
            "WHERE delivery_id = ?",
            (1.0, 1.0, "stale-1"),
        )

    bus = MessageBus(outbox_store=SQLiteOutboxStore(path), outbox_recovery_window_s=60)

    assert bus.outbound.consume_one() is None
    assert bus.outbox_store is not None
    record = bus.outbox_store.get("stale-1")
    assert record is not None
    assert record.status == "expired"


def test_fresh_outbox_is_recovered_with_original_event_time(tmp_path: Path):
    """恢复消息应携带本地生成时间，供渠道展示事件发生时间。"""

    path = tmp_path / "outbox.db"
    store = SQLiteOutboxStore(path)
    store.prepare(
        delivery_id="fresh-1",
        channel="telegram",
        session_id="session-1",
        chat_id="12345",
        text="新鲜消息",
        metadata={"kind": "proactive"},
    )

    bus = MessageBus(
        outbox_store=SQLiteOutboxStore(path), outbox_recovery_window_s=86400
    )
    restored = bus.outbound.consume_one()

    assert restored is not None
    assert restored.metadata["kind"] == "proactive"
    assert isinstance(restored.metadata["outbox_created_at"], float)


def test_sending_record_becomes_unknown_instead_of_replayed(tmp_path: Path):
    path = tmp_path / "outbox.db"
    store = SQLiteOutboxStore(path)
    store.prepare(
        delivery_id="sending-1",
        channel="telegram",
        session_id="session-1",
        chat_id="12345",
        text="结果未知",
        metadata={},
    )
    store.mark_sending("sending-1")

    restarted = SQLiteOutboxStore(path)
    bus = MessageBus(outbox_store=restarted)
    record = restarted.get("sending-1")

    assert record is not None
    assert record.status == "unknown"
    assert bus.outbound.consume_one() is None


def test_partial_channel_delivery_is_recorded_as_unknown(tmp_path: Path):
    async def scenario():
        store = SQLiteOutboxStore(tmp_path / "outbox.db")
        bus = MessageBus(outbox_store=store)
        bus.subscribe_outbound(
            "telegram",
            lambda message: ChannelDeliveryResult(
                delivered=False,
                retryable=False,
                uncertain=True,
                error=f"partial:{message.delivery_id}",
            ),
        )
        runner = asyncio.create_task(bus.start_dispatch_task())
        try:
            receipt = await bus.outbound_port.send_and_wait(
                OutboundDispatch(
                    channel="telegram",
                    session_id="session-1",
                    chat_id="12345",
                    text="部分送达",
                ),
                timeout=2,
            )
            assert receipt.delivered is False
            assert receipt.uncertain is True
            record = store.get(receipt.delivery_id)
            assert record is not None
            assert record.status == "unknown"
        finally:
            await bus.stop_dispatch_task()
            await runner

    asyncio.run(scenario())


def test_same_session_messages_are_processed_in_fifo_order():
    async def scenario():
        bus = MessageBus()
        processed = []
        release_first = asyncio.Event()

        class Pipeline:
            def process(self, inbound):
                del inbound

        loop: Any = AgentLoop(cast(Any, bus), cast(Any, Pipeline()), poll_interval_ms=1)

        async def fake_process(inbound):
            processed.append(f"start:{inbound.text}")
            if inbound.text == "first":
                await release_first.wait()
            processed.append(f"end:{inbound.text}")

        loop._process_async = fake_process
        runner = asyncio.create_task(loop.run_forever())
        bus.publish_inbound(
            InboundMessage(channel="telegram", session_id="s1", text="first")
        )
        bus.publish_inbound(
            InboundMessage(channel="telegram", session_id="s1", text="second")
        )
        await asyncio.sleep(0.03)

        assert processed == ["start:first"]
        assert loop.pending_message_count == 1

        release_first.set()
        deadline = asyncio.get_running_loop().time() + 1
        while len(processed) < 4 and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)

        assert processed == ["start:first", "end:first", "start:second", "end:second"]
        runner.cancel()
        try:
            await runner
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())


def test_telegram_long_reply_is_split_without_truncation(monkeypatch):
    channel = TelegramChannel("test-token")
    sent = []

    def fake_send(chat_id, text, max_retries=3):
        del chat_id, max_retries
        sent.append(text)
        return {"ok": True}

    monkeypatch.setattr(channel, "_send_text", fake_send)
    text = ("一段较长内容\n" * 900) + "结束"

    delivered = channel.on_outbound(
        OutboundMessage(
            channel="telegram",
            session_id="12345",
            chat_id="12345",
            delivery_id="delivery-1",
            text=text,
        )
    )

    assert delivered.delivered is True
    assert len(sent) > 1
    assert all(len(chunk) <= 3900 for chunk in sent)
    assert "".join(sent) == text


def test_telegram_retry_resumes_from_failed_chunk(monkeypatch):
    channel = TelegramChannel("test-token")
    payload_text = ("甲" * 3900) + ("乙" * 3900) + ("丙" * 200)
    calls = []
    fail_second_once = {"value": True}

    def fake_send(chat_id, text, max_retries=3):
        del chat_id, max_retries
        calls.append(text)
        if len(calls) == 2 and fail_second_once["value"]:
            fail_second_once["value"] = False
            return {}
        return {"ok": True}

    monkeypatch.setattr(channel, "_send_text", fake_send)
    message = OutboundMessage(
        channel="telegram",
        session_id="12345",
        chat_id="12345",
        delivery_id="delivery-retry",
        text=payload_text,
    )

    first_result = channel.on_outbound(message)
    assert first_result.delivered is False
    assert first_result.uncertain is True
    assert channel.on_outbound(message).delivered is True
    assert calls[0] == "甲" * 3900
    assert calls[1] == "乙" * 3900
    assert calls[2] == "乙" * 3900
    assert calls[3] == "丙" * 200


def test_proactive_side_effects_wait_for_real_delivery():
    class RejectedPort:
        async def send_and_wait(self, dispatch, timeout=30.0):
            del dispatch, timeout
            return type("Receipt", (), {"delivered": False, "error": "rejected"})()

    effects = []
    resolve = ResolveResult(
        decision="send",
        message="主动消息",
        side_effects=[lambda: effects.append("committed")],
    )

    result = asyncio.run(
        deliver_message(
            resolve,
            chat_id="12345",
            channel="telegram",
            outbound_port=RejectedPort(),
        )
    )

    assert result.sent is False
    assert effects == []


def test_spawn_tool_preserves_group_session_and_chat_target():
    from application.delegation.app.spawn import SpawnTool

    class Policy:
        def decide(self, **kwargs):
            del kwargs
            return type("Decision", (), {"action": "spawn_subagent", "reason": "ok"})()

    class Manager:
        def run_spawn_threadsafe(self, **kwargs):
            self.arguments = kwargs
            return "created"

    manager = Manager()
    tool = SpawnTool(manager=manager, policy=cast(Any, Policy()))
    result = tool.run(
        {
            "task": "群聊后台任务",
            "__channel": "telegram",
            "__chat_id": "-100123",
            "__session_id": "telegram_group_-100123",
        }
    )

    assert result.ok is True
    assert manager.arguments["origin_chat_id"] == "-100123"
    assert manager.arguments["origin_session_id"] == "telegram_group_-100123"


def test_agent_loop_cancellation_cancels_hanging_passive_turn():
    """运行时取消主循环时，必须取消尚未结束的被动回合。"""

    async def scenario():
        bus = MessageBus()

        class Pipeline:
            def process(self, inbound):
                del inbound

        loop: Any = AgentLoop(cast(Any, bus), cast(Any, Pipeline()), poll_interval_ms=1)
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def hanging_process(inbound):
            del inbound
            started.set()
            try:
                await asyncio.Future()
            finally:
                cancelled.set()

        loop._process_async = hanging_process
        runner = asyncio.create_task(loop.run_forever())
        bus.publish_inbound(InboundMessage(channel="cli", session_id="s1", text="hang"))
        await started.wait()
        runner.cancel()

        await asyncio.wait_for(runner, timeout=0.5)

        assert cancelled.is_set()
        assert loop.active_task_count == 0

    asyncio.run(scenario())

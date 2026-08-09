"""Telegram 对话主链路的集成契约测试。"""

import asyncio
from types import SimpleNamespace


def test_runner_uses_async_conversation_pipeline_for_telegram_input():
    """Telegram 入站消息必须交给对话管道的异步入口处理。"""

    from bootstrap.container import create_passive_loop
    from infra.bus.types import InboundMessage
    from application.passive.domain.messages import IncomingMessage
    from infra.bus.message import MessageBus

    class Pipeline:
        def __init__(self) -> None:
            self.received: list[IncomingMessage] = []
            self.done = asyncio.Event()

        async def process_async(self, message: IncomingMessage) -> None:
            self.received.append(message)
            self.done.set()

    async def scenario() -> None:
        bus = MessageBus()
        pipeline = Pipeline()
        runner = create_passive_loop(bus, pipeline)
        running = asyncio.create_task(runner.run_forever())
        try:
            bus.publish_inbound(
                InboundMessage(
                    channel="telegram",
                    session_id="42",
                    text="你好",
                    sender="42",
                    chat_id="42",
                    metadata={"provider_user_id": 42},
                )
            )
            await asyncio.wait_for(pipeline.done.wait(), timeout=0.5)
            assert pipeline.received[0].channel == "telegram"
            assert pipeline.received[0].conversation_id == "42"
            assert pipeline.received[0].text == "你好"
            assert pipeline.received[0].metadata == {"provider_user_id": 42}
        finally:
            await runner.stop()
            await asyncio.wait_for(running, timeout=0.5)

    asyncio.run(scenario())


def test_telegram_update_runs_conversation_and_delivers_reply():
    """Telegram 更新必须经过对话应用并回到同一个 chat_id。"""

    from interfaces.channels.telegram import TelegramChannel
    from application.agent.app.loop import AgentLoop
    from infra.bus.types import SendMessage
    from infra.bus.message import MessageBus

    async def scenario() -> None:
        bus = MessageBus()
        channel = TelegramChannel("test-token")
        sent: list[tuple[int, str]] = []
        channel._send_text = lambda chat_id, text, max_retries=3: (
            sent.append((chat_id, text)) or {"ok": True}
        )
        channel._context = SimpleNamespace(
            bus=bus,
            event_bus=SimpleNamespace(subscribe=lambda subscriber: None),
            log=SimpleNamespace(),
        )
        bus.subscribe_outbound(channel.name, channel.on_outbound)

        processed = asyncio.Event()

        class Processor:
            async def process_async(self, message) -> None:
                assert message.channel == "telegram"
                assert message.conversation_id == "42"
                assert message.chat_id == "42"
                result = bus.send(
                    SendMessage(
                        channel=message.channel,
                        conversation_id=message.conversation_id,
                        recipient_id=message.chat_id,
                        text=f"收到：{message.text}",
                    )
                )
                assert result.accepted is True
                processed.set()

        runner = AgentLoop(bus, Processor(), poll_interval_ms=1)
        dispatching = asyncio.create_task(bus.start_dispatch_task())
        running = asyncio.create_task(runner.run_forever())
        try:
            await channel._handle_update(
                {
                    "message": {
                        "message_id": 1,
                        "chat": {"id": 42, "type": "private"},
                        "from": {"id": 42, "username": "user"},
                        "text": "你好",
                    }
                }
            )
            await asyncio.wait_for(processed.wait(), timeout=1)
            deadline = asyncio.get_running_loop().time() + 1
            while (
                sent != [(42, "收到：你好")]
                and asyncio.get_running_loop().time() < deadline
            ):
                await asyncio.sleep(0.01)
            assert sent == [(42, "收到：你好")]
        finally:
            await runner.stop()
            await asyncio.wait_for(running, timeout=1)
            await bus.stop_dispatch_task()
            await asyncio.wait_for(dispatching, timeout=1)

    asyncio.run(scenario())


def test_conversation_runner_background_thread_stops_cleanly():
    """后台对话运行器停止后不得遗留事件循环线程。"""

    import time

    from application.agent.app.loop import AgentLoop

    class Source:
        async def receive(self, poll_interval_ms: int):
            del poll_interval_ms
            await asyncio.sleep(10)
            raise AssertionError("测试源不应返回消息")

    class Processor:
        async def process_async(self, message) -> None:
            del message

    runner = AgentLoop(Source(), Processor(), poll_interval_ms=1)
    runner.start_background()
    deadline = time.monotonic() + 1
    while not runner.running and time.monotonic() < deadline:
        time.sleep(0.01)

    runner.stop_background()

    assert runner.running is False
    assert runner._thread is None or not runner._thread.is_alive()


def test_telegram_channel_stop_removes_bus_subscriptions():
    """Telegram 渠道停止时必须撤销出站和事件订阅。"""

    from infra.bus.event import EventBus
    from interfaces.channels.telegram import TelegramChannel
    from infra.bus.message import MessageBus

    async def scenario() -> None:
        bus = MessageBus()
        event_bus = EventBus()
        channel = TelegramChannel("test-token")
        channel._context = SimpleNamespace(bus=bus, event_bus=event_bus, log=None)
        channel._running = True
        channel._subscribed = True
        bus.subscribe_outbound(channel.name, channel.on_outbound)
        event_bus.subscribe(channel)

        channel.stop()

        assert bus.outbound.subscriber_count == 0
        assert event_bus.subscriber_count == 0

    asyncio.run(scenario())

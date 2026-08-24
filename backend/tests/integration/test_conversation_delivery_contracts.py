from datetime import datetime, timezone
import asyncio


def test_conversation_message_preserves_channel_session_and_media():
    """渠道适配后的入站消息必须保留会话、发送者与媒体信息。"""

    from application.passive.domain.messages import IncomingMessage

    received_at = datetime(2026, 8, 2, tzinfo=timezone.utc)
    message = IncomingMessage(
        channel="telegram",
        conversation_id="telegram:42",
        text="你好",
        sender_id="42",
        media=("/tmp/image.png",),
        received_at=received_at,
        metadata={"chat_id": "42"},
    )

    assert message.channel == "telegram"
    assert message.conversation_id == "telegram:42"
    assert message.sender_id == "42"
    assert message.media == ("/tmp/image.png",)
    assert message.received_at == received_at


def test_message_send_preserves_a_stable_message_identity():
    """业务发送端口必须保留调用方提供的稳定消息标识。"""

    from infra.bus.types import SendMessage
    from infra.bus.message import MessageBus

    message = SendMessage(
        channel="telegram",
        conversation_id="telegram:42",
        text="回复",
        recipient_id="42",
        message_id="message-1",
    )
    result = MessageBus().send(message)

    assert result.message_id == "message-1"
    assert result.accepted is True


def test_conversation_runner_serializes_one_conversation_without_blocking_another():
    """同一会话必须 FIFO，不同会话在前一回合等待时仍可处理。"""

    from application.agent.app.loop import AgentLoop
    from application.passive.domain.messages import IncomingMessage
    from infra.bus.types import ReceivedMessage

    class Source:
        def __init__(self) -> None:
            self.messages: asyncio.Queue[ReceivedMessage] = asyncio.Queue()

        async def receive(self, poll_interval_ms: int) -> ReceivedMessage:
            del poll_interval_ms
            return await self.messages.get()

        async def ack(self, message_id: str) -> None:
            del message_id

        async def nack(self, message_id: str, *, retry: bool = True) -> None:
            del message_id, retry

    class Processor:
        def __init__(self) -> None:
            self.first_started = asyncio.Event()
            self.release_first = asyncio.Event()
            self.steps: list[str] = []

        async def process(self, message: IncomingMessage) -> None:
            self.steps.append(f"start:{message.text}")
            if message.text == "first":
                self.first_started.set()
                await self.release_first.wait()
            self.steps.append(f"end:{message.text}")

    async def scenario() -> None:
        source = Source()
        processor = Processor()
        runner = AgentLoop(source, processor, poll_interval_ms=1)
        task = asyncio.create_task(runner.run_forever())
        try:
            await source.messages.put(
                ReceivedMessage("1", "text", "cli", "same", "first")
            )
            await asyncio.wait_for(processor.first_started.wait(), timeout=0.2)
            assert runner.is_processing("same") is True
            assert runner.is_processing("other") is False
            await source.messages.put(
                ReceivedMessage("2", "text", "cli", "same", "second")
            )
            await source.messages.put(
                ReceivedMessage("3", "text", "cli", "other", "parallel")
            )
            deadline = asyncio.get_running_loop().time() + 0.2
            while "end:parallel" not in processor.steps:
                if asyncio.get_running_loop().time() > deadline:
                    raise TimeoutError("另一会话未并发处理")
                await asyncio.sleep(0.005)
            assert processor.steps == ["start:first", "start:parallel", "end:parallel"]
            processor.release_first.set()
            deadline = asyncio.get_running_loop().time() + 0.2
            while len(processor.steps) < 6:
                if asyncio.get_running_loop().time() > deadline:
                    raise TimeoutError("同一会话未继续处理")
                await asyncio.sleep(0.005)
            assert processor.steps == [
                "start:first",
                "start:parallel",
                "end:parallel",
                "end:first",
                "start:second",
                "end:second",
            ]
        finally:
            processor.release_first.set()
            await runner.stop()
            await asyncio.wait_for(task, timeout=0.2)

    asyncio.run(scenario())


def test_conversation_runner_cancels_hanging_turn_after_stop_timeout():
    """停止超时后必须取消卡住的回合，不能遗留后台任务。"""

    from application.agent.app.loop import AgentLoop
    from application.passive.domain.messages import IncomingMessage
    from infra.bus.types import ReceivedMessage

    class Source:
        def __init__(self) -> None:
            self.messages: asyncio.Queue[ReceivedMessage] = asyncio.Queue()

        async def receive(self, poll_interval_ms: int) -> ReceivedMessage:
            del poll_interval_ms
            return await self.messages.get()

        async def ack(self, message_id: str) -> None:
            del message_id

        async def nack(self, message_id: str, *, retry: bool = True) -> None:
            del message_id, retry

    class Processor:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def process(self, message: IncomingMessage) -> None:
            del message
            self.started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

    async def scenario() -> None:
        source = Source()
        processor = Processor()
        runner = AgentLoop(source, processor, poll_interval_ms=1)
        running = asyncio.create_task(runner.run_forever())
        await source.messages.put(ReceivedMessage("1", "text", "cli", "same", "hang"))
        await asyncio.wait_for(processor.started.wait(), timeout=0.2)

        await runner.stop(timeout=0.01)
        await asyncio.wait_for(running, timeout=0.2)

        assert processor.cancelled.is_set()
        assert runner.active_task_count == 0

    asyncio.run(scenario())


def test_message_consumer_translates_channel_input_to_received_message():
    """消息消费者负责把渠道输入转换为统一的入站消息。"""

    from infra.bus.types import InboundMessage
    from infra.bus.message import MessageBus

    async def scenario() -> None:
        bus = MessageBus()
        bus.publish_inbound(
            InboundMessage(
                channel="cli",
                session_id="cli:1",
                text="迁移输入",
                sender="user-1",
                media=["/tmp/file.txt"],
                metadata={"kind": "text"},
            )
        )

        message = await bus.receive(poll_interval_ms=1)

        assert message.conversation_id == "cli:1"
        assert message.sender_id == "user-1"
        assert message.media == ("/tmp/file.txt",)
        assert message.metadata == {"kind": "text"}

    asyncio.run(scenario())


def test_bootstrap_assembles_the_new_conversation_runner():
    """组合根必须将既有消息总线接入新的对话应用运行器。"""

    from bootstrap.container import create_passive_loop
    from infra.bus.message import MessageBus
    from application.agent.app.loop import AgentLoop

    class Pipeline:
        async def process_async(self, message) -> None:
            del message

    runner = create_passive_loop(MessageBus(), Pipeline())

    assert isinstance(runner, AgentLoop)


def test_message_bus_send_reaches_the_channel_dispatcher():
    """消息发送端口提交的消息必须进入渠道分发器。"""

    from infra.bus.message import MessageBus
    from infra.bus.types import SendMessage

    async def scenario() -> None:
        bus = MessageBus()
        delivered_to = []
        bus.subscribe_outbound(
            "telegram",
            lambda message: delivered_to.append(message.chat_id) or True,
        )
        runner = asyncio.create_task(bus.start_dispatch_task())
        try:
            result = bus.send(
                SendMessage(
                    channel="telegram",
                    conversation_id="telegram:42",
                    recipient_id="42",
                    text="回复",
                    message_id="message-42",
                ),
            )
            assert result.accepted is True
            deadline = asyncio.get_running_loop().time() + 1
            while (
                delivered_to != ["42"] and asyncio.get_running_loop().time() < deadline
            ):
                await asyncio.sleep(0.01)
            assert delivered_to == ["42"]
        finally:
            await bus.stop_dispatch_task()
            await runner

    asyncio.run(scenario())


def test_passive_pipeline_submits_reply_through_message_sender():
    """被动回复必须经 MessageSender 提交，不能直接依赖渠道投递对象。"""

    from types import SimpleNamespace

    from application.passive.app.pipeline import PassiveTurnPipeline
    from application.capabilities.tools.registry import ToolRegistry
    from infra.bus.types import SendMessage

    submitted: list[SendMessage] = []

    class Sender:
        def send(self, message: SendMessage):
            submitted.append(message)
            return SimpleNamespace(message_id=message.message_id, accepted=True)

    pipeline = PassiveTurnPipeline(
        agent=object(),
        tool_registry=ToolRegistry(),
        message_sender=Sender(),
    )
    flow = SimpleNamespace(
            channel="telegram",
            session_id="telegram:42",
            chat_id="42",
            final_output="回复",
        trace_id="trace-1",
        tool_trace=[],
        inbound_metadata={"telegram_chat_id": "42"},
    )

    pipeline._send_outbound_reply(flow)

    assert submitted == [
        SendMessage(
            channel="telegram",
            conversation_id="42",
            recipient_id="42",
            text="回复",
            message_id="trace-1",
            metadata={
                "trace_id": "trace-1",
                "tool_trace": [],
                "telegram_chat_id": "42",
            },
        )
    ]

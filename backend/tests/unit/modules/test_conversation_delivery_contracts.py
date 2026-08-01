from datetime import datetime, timezone
import asyncio


def test_conversation_message_preserves_channel_session_and_media():
    """渠道适配后的入站消息必须保留会话、发送者与媒体信息。"""

    from modules.conversation.domain.messages import IncomingMessage

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


def test_delivery_request_creates_a_stable_receipt_identity():
    """投递端口必须使用请求的稳定标识返回回执，供调用方关联结果。"""

    from modules.delivery.application.ports import DeliveryReceipt, DeliveryRequest

    request = DeliveryRequest(
        channel="telegram",
        conversation_id="telegram:42",
        text="回复",
        recipient_id="42",
        delivery_id="delivery-1",
    )
    receipt = DeliveryReceipt.delivered_for(request, attempts=1)

    assert receipt.delivery_id == "delivery-1"
    assert receipt.delivered is True
    assert receipt.attempts == 1


def test_conversation_runner_serializes_one_conversation_without_blocking_another():
    """同一会话必须 FIFO，不同会话在前一回合等待时仍可处理。"""

    from modules.conversation.application.runner import ConversationRunner
    from modules.conversation.domain.messages import IncomingMessage

    class Source:
        def __init__(self) -> None:
            self.messages: asyncio.Queue[IncomingMessage] = asyncio.Queue()

        async def receive(self, poll_interval_ms: int) -> IncomingMessage:
            del poll_interval_ms
            return await self.messages.get()

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
        runner = ConversationRunner(source, processor, poll_interval_ms=1)
        task = asyncio.create_task(runner.run_forever())
        try:
            await source.messages.put(IncomingMessage("cli", "same", "first"))
            await asyncio.wait_for(processor.first_started.wait(), timeout=0.2)
            assert runner.is_processing("same") is True
            assert runner.is_processing("other") is False
            await source.messages.put(IncomingMessage("cli", "same", "second"))
            await source.messages.put(IncomingMessage("cli", "other", "parallel"))
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


def test_legacy_pipeline_adapter_translates_the_new_conversation_contract():
    """迁移适配器必须完整转换新入站协议，避免旧字段泄漏到应用层。"""

    from modules.conversation.domain.messages import IncomingMessage
    from modules.conversation.infra.legacy_pipeline import LegacyPipelineProcessor

    received = []

    class Pipeline:
        async def process_async(self, message) -> None:
            received.append(message)

    async def scenario() -> None:
        adapter = LegacyPipelineProcessor(Pipeline())
        await adapter.process(
            IncomingMessage(
                channel="telegram",
                conversation_id="telegram:42",
                text="你好",
                sender_id="42",
                media=("/tmp/image.png",),
                metadata={"chat_id": "42"},
            )
        )

    asyncio.run(scenario())

    assert received[0].channel == "telegram"
    assert received[0].session_id == "telegram:42"
    assert received[0].sender == "42"
    assert received[0].media == ["/tmp/image.png"]
    assert received[0].metadata == {"chat_id": "42"}


def test_legacy_message_bus_source_translates_channel_input_to_conversation_input():
    """现有消息总线进入新应用层前必须完成协议转换。"""

    from flow_agent.channels.models import InboundMessage
    from flow_agent.messaging.message_bus import MessageBus
    from modules.conversation.infra.legacy_message_bus import LegacyMessageBusSource

    async def scenario() -> None:
        bus = MessageBus()
        source = LegacyMessageBusSource(bus)
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

        message = await source.receive(poll_interval_ms=1)

        assert message.conversation_id == "cli:1"
        assert message.sender_id == "user-1"
        assert message.media == ("/tmp/file.txt",)
        assert message.metadata == {"kind": "text"}

    asyncio.run(scenario())


def test_bootstrap_assembles_the_new_conversation_runner():
    """组合根必须将既有消息总线接入新的对话应用运行器。"""

    from flow_agent.app.bootstrap import create_agent_loop
    from flow_agent.messaging.message_bus import MessageBus
    from modules.conversation.application.runner import ConversationRunner

    class Pipeline:
        async def process_async(self, message) -> None:
            del message

    runner = create_agent_loop(MessageBus(), Pipeline())

    assert isinstance(runner, ConversationRunner)


def test_delivery_adapter_returns_the_real_channel_receipt():
    """投递适配器必须把渠道确认结果转换为业务回执，而非提前报告成功。"""

    from flow_agent.messaging.message_bus import MessageBus
    from modules.delivery.application.ports import DeliveryRequest
    from modules.delivery.infra.legacy_message_bus import LegacyMessageBusDeliveryPort

    async def scenario() -> None:
        bus = MessageBus()
        port = LegacyMessageBusDeliveryPort(bus)
        delivered_to = []
        bus.subscribe_outbound(
            "telegram",
            lambda message: delivered_to.append(message.chat_id) or True,
        )
        runner = asyncio.create_task(bus.start_dispatch_task())
        try:
            receipt = await port.send_and_wait(
                DeliveryRequest(
                    channel="telegram",
                    conversation_id="telegram:42",
                    recipient_id="42",
                    text="回复",
                    delivery_id="delivery-42",
                ),
                timeout=1,
            )
            assert receipt.delivery_id == "delivery-42"
            assert receipt.delivered is True
            assert delivered_to == ["42"]
        finally:
            await bus.stop_dispatch_task()
            await runner

    asyncio.run(scenario())


def test_passive_pipeline_submits_reply_through_the_delivery_port():
    """被动回复必须经 DeliveryPort 提交，不能直接依赖渠道投递对象。"""

    from types import SimpleNamespace

    from flow_agent.core.passive_turn_pipeline import PassiveTurnPipeline
    from flow_agent.tools.registry import ToolRegistry
    from modules.delivery.application.ports import DeliveryRequest

    submitted: list[DeliveryRequest] = []

    class Port:
        def submit(self, request: DeliveryRequest) -> None:
            submitted.append(request)

    pipeline = PassiveTurnPipeline(
        agent=object(),
        tool_registry=ToolRegistry(),
        delivery_port=Port(),
    )
    flow = SimpleNamespace(
        channel="telegram",
        session_id="telegram:42",
        final_output="回复",
        trace_id="trace-1",
        tool_trace=[],
        inbound_metadata={"telegram_chat_id": "42"},
    )

    pipeline._send_outbound_reply(flow)

    assert submitted == [
        DeliveryRequest(
            channel="telegram",
            conversation_id="telegram:42",
            recipient_id="42",
            text="回复",
            metadata={
                "trace_id": "trace-1",
                "tool_trace": [],
                "telegram_chat_id": "42",
            },
        )
    ]

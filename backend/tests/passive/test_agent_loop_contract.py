from __future__ import annotations

import asyncio

from application.agent.app.loop import AgentLoop
from infra.bus.event import EventBus
from infra.bus.types import ReceivedMessage


class QueueConsumer:
    def __init__(self) -> None:
        self.messages: asyncio.Queue[ReceivedMessage] = asyncio.Queue()
        self.acked: list[str] = []
        self.nacked: list[str] = []

    async def receive(self, poll_interval_ms: int = 100) -> ReceivedMessage:
        del poll_interval_ms
        return await self.messages.get()

    async def ack(self, message_id: str) -> None:
        self.acked.append(message_id)

    async def nack(self, message_id: str, *, retry: bool = True) -> None:
        del retry
        self.nacked.append(message_id)


def test_agent_loop_consumes_processes_and_acks_messages() -> None:
    async def scenario() -> None:
        consumer = QueueConsumer()
        processed: list[str] = []

        class Processor:
            async def process_async(self, message) -> None:
                processed.append(message.text)

        loop = AgentLoop(
            consumer=consumer,
            processor=Processor(),
            event_bus=EventBus(),
            poll_interval_ms=1,
        )
        runner = asyncio.create_task(loop.run_forever())
        await consumer.messages.put(
            ReceivedMessage(
                message_id="message-1",
                kind="conversation.input",
                channel="cli",
                conversation_id="conversation-1",
                text="你好",
            )
        )

        deadline = asyncio.get_running_loop().time() + 1
        while not consumer.acked and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)

        await loop.stop()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)

        assert processed == ["你好"]
        assert consumer.acked == ["message-1"]
        assert consumer.nacked == []

    asyncio.run(scenario())


def test_agent_loop_skips_duplicate_provider_message() -> None:
    async def scenario() -> None:
        consumer = QueueConsumer()
        processed: list[str] = []

        class Processor:
            async def process_async(self, message) -> None:
                processed.append(message.text)

        loop = AgentLoop(consumer=consumer, processor=Processor(), poll_interval_ms=1)
        runner = asyncio.create_task(loop.run_forever())
        for message_id in ("bus-1", "bus-2"):
            await consumer.messages.put(
                ReceivedMessage(
                    message_id=message_id,
                    kind="conversation.input",
                    channel="telegram",
                    conversation_id="conversation-1",
                    text="重复消息",
                    metadata={"message_id": "telegram-100"},
                )
            )

        deadline = asyncio.get_running_loop().time() + 1
        while len(consumer.acked) < 2 and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)

        await loop.stop()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)

        assert processed == ["重复消息"]
        assert consumer.acked == ["bus-1", "bus-2"]

    asyncio.run(scenario())


def test_agent_loop_skips_same_text_in_short_window() -> None:
    async def scenario() -> None:
        consumer = QueueConsumer()
        processed: list[str] = []

        class Processor:
            async def process_async(self, message) -> None:
                processed.append(message.text)

        loop = AgentLoop(consumer=consumer, processor=Processor(), poll_interval_ms=1)
        runner = asyncio.create_task(loop.run_forever())
        for message_id in ("bus-1", "bus-2"):
            await consumer.messages.put(
                ReceivedMessage(
                    message_id=message_id,
                    kind="conversation.input",
                    channel="cli",
                    conversation_id="conversation-1",
                    text="  同一问题  ",
                )
            )

        deadline = asyncio.get_running_loop().time() + 1
        while len(consumer.acked) < 2 and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)

        await loop.stop()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)

        assert processed == ["  同一问题  "]
        assert consumer.acked == ["bus-1", "bus-2"]

    asyncio.run(scenario())


def test_agent_loop_skips_same_text_with_different_provider_ids() -> None:
    async def scenario() -> None:
        consumer = QueueConsumer()
        processed: list[str] = []

        class Processor:
            async def process_async(self, message) -> None:
                processed.append(message.text)

        loop = AgentLoop(consumer=consumer, processor=Processor(), poll_interval_ms=1)
        runner = asyncio.create_task(loop.run_forever())
        for index in range(2):
            await consumer.messages.put(
                ReceivedMessage(
                    message_id=f"bus-{index}",
                    kind="conversation.input",
                    channel="telegram",
                    conversation_id="conversation-1",
                    text="在吗",
                    sender_id="user-1",
                    metadata={"message_id": f"telegram-{index}"},
                )
            )

        deadline = asyncio.get_running_loop().time() + 1
        while len(consumer.acked) < 2 and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)

        await loop.stop()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)

        assert processed == ["在吗"]
        assert consumer.acked == ["bus-0", "bus-1"]

    asyncio.run(scenario())

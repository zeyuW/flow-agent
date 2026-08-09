"""聊天工作器的消息消费与确认契约。"""

import asyncio


def test_agent_loop_consumes_message_processes_it_and_acknowledges_it():
    """处理成功后必须确认消息，避免同一消息被重复消费。"""

    from application.agent.app.loop import AgentLoop
    from infra.bus.types import ReceivedMessage

    class Consumer:
        def __init__(self) -> None:
            self.messages = asyncio.Queue()
            self.acks: list[str] = []
            self.nacks: list[str] = []

        async def receive(self, poll_interval_ms: int = 100) -> ReceivedMessage:
            del poll_interval_ms
            return await self.messages.get()

        async def ack(self, message_id: str) -> None:
            self.acks.append(message_id)

        async def nack(self, message_id: str, *, retry: bool = True) -> None:
            del retry
            self.nacks.append(message_id)

    class Processor:
        def __init__(self) -> None:
            self.received = []
            self.done = asyncio.Event()

        async def process_async(self, message) -> None:
            self.received.append(message)
            self.done.set()

    async def scenario() -> None:
        consumer = Consumer()
        processor = Processor()
        worker = AgentLoop(consumer, processor, poll_interval_ms=1)
        running = asyncio.create_task(worker.run_forever())
        try:
            await consumer.messages.put(
                ReceivedMessage(
                    message_id="message-1",
                    kind="conversation.input",
                    channel="telegram",
                    conversation_id="telegram:42",
                    text="你好",
                    sender_id="42",
                    metadata={"telegram_chat_id": 42},
                )
            )
            await asyncio.wait_for(processor.done.wait(), timeout=0.5)
            deadline = asyncio.get_running_loop().time() + 0.5
            while not consumer.acks and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.005)
            assert consumer.acks == ["message-1"]
            assert consumer.nacks == []
            assert processor.received[0].conversation_id == "telegram:42"
        finally:
            await worker.stop()
            await asyncio.wait_for(running, timeout=0.5)

    asyncio.run(scenario())

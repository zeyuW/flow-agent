"""被动回合并发与会话隔离测试。"""

import asyncio

from interfaces.channels.models import InboundMessage
from modules.conversation.application.agent_loop import AgentLoop
from modules.delivery.infra.delivery_bus import DeliveryBus


def test_different_sessions_start_without_waiting_for_each_other():
    """一个会话等待模型时，另一会话必须能够开始执行。"""

    async def scenario():
        bus = DeliveryBus()
        first_started = asyncio.Event()
        second_started = asyncio.Event()
        release_first = asyncio.Event()

        class Pipeline:
            async def process_async(self, inbound):
                if inbound.session_id == "session-1":
                    first_started.set()
                    await release_first.wait()
                    return
                second_started.set()

        loop = AgentLoop(bus, Pipeline(), poll_interval_ms=1)
        runner = asyncio.create_task(loop.run_forever())
        try:
            bus.publish_inbound(
                InboundMessage(channel="cli", session_id="session-1", text="first")
            )
            await asyncio.wait_for(first_started.wait(), timeout=0.2)

            bus.publish_inbound(
                InboundMessage(channel="cli", session_id="session-2", text="second")
            )
            await asyncio.wait_for(second_started.wait(), timeout=0.2)
        finally:
            release_first.set()
            await loop.stop(timeout=0.2)
            await asyncio.wait_for(runner, timeout=0.2)

    asyncio.run(scenario())


def test_agent_builds_history_for_explicit_session():
    """并发回合必须按调用参数读取对应会话历史。"""

    from modules.conversation.application.agent import Agent
    from modules.conversation.infra.context import ConversationContext

    context = ConversationContext()
    context.append_turn("session-a", "仅属于 A 的用户消息", "仅属于 A 的回复")
    context.append_turn("session-b", "仅属于 B 的用户消息", "仅属于 B 的回复")
    agent = Agent(
        system_prompt="系统提示",
        llm_client=object(),
        context=context,
    )

    messages = agent.build_turn_messages(
        "当前请求",
        session_id="session-b",
    )
    rendered = "\n".join(message["content"] for message in messages)

    assert "仅属于 B 的用户消息" in rendered
    assert "仅属于 A 的用户消息" not in rendered


def test_agent_awaits_async_model_client():
    """Agent 必须通过异步模型接口等待模型结果。"""

    from types import SimpleNamespace

    from modules.conversation.application.agent import Agent
    from modules.conversation.infra.context import ConversationContext
    from modules.capabilities.llm.client import LLMResult

    class AsyncClient:
        async def generate_async(self, messages, tools=None):
            del messages, tools
            return LLMResult(content="异步结果")

    agent = Agent(
        system_prompt="系统提示",
        llm_client=AsyncClient(),
        context=ConversationContext(),
    )

    result = asyncio.run(
        agent.generate_from_messages_async(
            [{"role": "user", "content": "请求"}],
        )
    )

    assert result.content == "异步结果"


def test_openai_client_generates_with_async_transport():
    """真实模型客户端必须通过异步传输生成结果。"""

    from types import SimpleNamespace

    from modules.capabilities.llm.client import OpenAILLMClient

    class Completions:
        async def create(self, **kwargs):
            assert kwargs["model"] == "test-model"
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="异步响应", tool_calls=[]),
                    )
                ]
            )

    client = object.__new__(OpenAILLMClient)
    client.model = "test-model"
    client.async_client = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions()),
    )

    result = asyncio.run(
        client.generate_async(
            [{"role": "user", "content": "请求"}],
        )
    )

    assert result.content == "异步响应"
    assert result.tool_calls is None


def test_passive_pipeline_allows_other_session_while_async_model_waits():
    """真实被动管道等待模型时，不得阻塞另一会话。"""

    from types import SimpleNamespace

    from modules.conversation.application.pipeline import PassiveTurnPipeline
    from modules.capabilities.llm.client import LLMResult
    from modules.capabilities.tools.registry import ToolRegistry

    async def scenario():
        first_model_started = asyncio.Event()
        release_first_model = asyncio.Event()
        committed = []

        class Agent:
            persona_resolver = None
            context = SimpleNamespace(get_history=lambda session_id: [])

            def build_turn_messages(self, user_input, **kwargs):
                del kwargs
                return [{"role": "user", "content": user_input}]

            async def generate_from_messages_async(self, messages, tools=None):
                del tools
                user_input = messages[-1]["content"]
                if user_input == "first":
                    first_model_started.set()
                    await release_first_model.wait()
                return LLMResult(content=f"reply:{user_input}")

            def commit_turn(self, user_input, assistant_output, *, session_id=None):
                committed.append((session_id, user_input, assistant_output))

        pipeline = PassiveTurnPipeline(
            agent=Agent(),
            tool_registry=ToolRegistry(),
        )
        first = asyncio.create_task(
            pipeline.process_async(
                InboundMessage(channel="cli", session_id="session-1", text="first")
            )
        )
        await asyncio.wait_for(first_model_started.wait(), timeout=0.2)

        second = asyncio.create_task(
            pipeline.process_async(
                InboundMessage(channel="cli", session_id="session-2", text="second")
            )
        )
        await asyncio.wait_for(second, timeout=0.2)
        release_first_model.set()
        await asyncio.wait_for(first, timeout=0.2)

        assert committed == [
            ("session-2", "second", "reply:second"),
            ("session-1", "first", "reply:first"),
        ]

    asyncio.run(scenario())


def test_cancelled_async_passive_turn_does_not_commit_reply():
    """取消等待模型的异步回合后，不得提交回复。"""

    from types import SimpleNamespace

    from modules.conversation.application.pipeline import PassiveTurnPipeline
    from modules.capabilities.tools.registry import ToolRegistry

    async def scenario():
        model_started = asyncio.Event()
        committed = []

        class Agent:
            persona_resolver = None
            context = SimpleNamespace(get_history=lambda session_id: [])

            def build_turn_messages(self, user_input, **kwargs):
                del kwargs
                return [{"role": "user", "content": user_input}]

            async def generate_from_messages_async(self, messages, tools=None):
                del messages, tools
                model_started.set()
                await asyncio.Future()

            def commit_turn(self, user_input, assistant_output, *, session_id=None):
                committed.append((session_id, user_input, assistant_output))

        pipeline = PassiveTurnPipeline(
            agent=Agent(),
            tool_registry=ToolRegistry(),
        )
        turn = asyncio.create_task(
            pipeline.process_async(
                InboundMessage(channel="cli", session_id="session-1", text="first")
            )
        )
        await asyncio.wait_for(model_started.wait(), timeout=0.2)
        turn.cancel()
        try:
            await turn
        except asyncio.CancelledError:
            pass

        assert committed == []

    asyncio.run(scenario())


def test_async_pipeline_applies_tool_hook_before_execution():
    """异步工具循环必须保留同步路径的插件钩子语义。"""

    from types import SimpleNamespace

    from modules.conversation.application.pipeline import PassiveTurnPipeline
    from modules.capabilities.llm.client import LLMResult, LLMToolCall
    from modules.capabilities.plugins.tool_hooks import HookOutcome, ToolHookExecutor
    from modules.capabilities.tools.base import ToolResult
    from modules.capabilities.tools.registry import ToolRegistry

    async def scenario():
        received = []

        class Tool:
            name = "echo"
            description = "回显"
            input_schema = {"type": "object", "properties": {"text": {"type": "string"}}}

            def run(self, tool_input):
                received.append(tool_input["text"])
                return ToolResult(ok=True, content=tool_input["text"])

        class Agent:
            persona_resolver = None
            context = SimpleNamespace(get_history=lambda session_id: [])

            def build_turn_messages(self, user_input, **kwargs):
                del kwargs
                return [{"role": "user", "content": user_input}]

            def commit_turn(self, user_input, assistant_output, *, session_id=None):
                del user_input, assistant_output, session_id

            async def generate_from_messages_async(self, messages, tools=None):
                del tools
                if len(messages) == 1:
                    return LLMResult(
                        content="",
                        tool_calls=[
                            LLMToolCall(
                                id="call-1",
                                name="echo",
                                arguments_json='{"text":"原始值"}',
                                arguments={"text": "原始值"},
                            )
                        ],
                    )
                return LLMResult(content="完成")

        hooks = ToolHookExecutor()
        hooks.register(
            _PluginToolHook(
                tool_name="echo",
                priority=0,
                plugin_id="demo",
                handler=lambda ctx: HookOutcome(
                    decision="modify",
                    modified_args={"text": "重写值"},
                ),
            )
        )
        registry = ToolRegistry()
        registry.register(Tool())
        pipeline = PassiveTurnPipeline(
            agent=Agent(),
            tool_registry=registry,
            tool_hook_executor=hooks,
        )

        await pipeline.process_async(
            InboundMessage(channel="cli", session_id="session-1", text="测试")
        )

        assert received == ["重写值"]

    from ..capabilities.plugins.test_plugin_pipeline_integration import _PluginToolHook
    asyncio.run(scenario())


def test_same_session_async_pipeline_keeps_fifo_order():
    """同一会话的后续消息必须等待前一回合终态。"""

    async def scenario():
        bus = DeliveryBus()
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        steps = []

        class Pipeline:
            async def process_async(self, inbound):
                steps.append(f"start:{inbound.text}")
                if inbound.text == "first":
                    first_started.set()
                    await release_first.wait()
                steps.append(f"end:{inbound.text}")

        loop = AgentLoop(bus, Pipeline(), poll_interval_ms=1)
        runner = asyncio.create_task(loop.run_forever())
        try:
            bus.publish_inbound(
                InboundMessage(channel="cli", session_id="session-1", text="first")
            )
            await asyncio.wait_for(first_started.wait(), timeout=0.2)
            bus.publish_inbound(
                InboundMessage(channel="cli", session_id="session-1", text="second")
            )
            await asyncio.sleep(0.03)

            assert steps == ["start:first"]
            release_first.set()
            deadline = asyncio.get_running_loop().time() + 0.2
            while len(steps) < 4 and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.005)
            assert steps == [
                "start:first",
                "end:first",
                "start:second",
                "end:second",
            ]
        finally:
            release_first.set()
            await loop.stop(timeout=0.2)
            await asyncio.wait_for(runner, timeout=0.2)

    asyncio.run(scenario())

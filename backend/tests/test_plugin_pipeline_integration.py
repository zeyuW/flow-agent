import asyncio
from types import SimpleNamespace

from flow_agent.channels.models import InboundMessage
from flow_agent.core.passive_turn_pipeline import PassiveTurnPipeline
from flow_agent.llm.client import LLMResult, LLMToolCall
from flow_agent.plugins.tool_hooks import HookOutcome, ToolHookExecutor, _PluginToolHook
from flow_agent.tools.base import ToolResult
from flow_agent.tools.registry import ToolRegistry


class _EchoTool:
    name = "echo"
    description = "回显输入"
    input_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def run(self, tool_input):
        return ToolResult(ok=True, content=tool_input["text"])


class _Agent:
    persona_resolver = None

    def __init__(self):
        self.context = SimpleNamespace(get_history=lambda session_id: [])
        self.calls = 0
        self.committed = None

    def set_session(self, session_id):
        self.session_id = session_id

    def build_turn_messages(self, **kwargs):
        return [{"role": "user", "content": kwargs["user_input"]}]

    def generate_from_messages(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return LLMResult(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-1",
                        name="echo",
                        arguments_json='{"text":"original"}',
                        arguments={"text": "original"},
                    )
                ],
            )
        assert "rewritten" in messages[-1]["content"]
        return LLMResult(content="完成")

    def commit_turn(self, user_input, assistant_output):
        self.committed = (user_input, assistant_output)


def test_plugin_phase_and_tool_hook_are_used_by_passive_pipeline():
    phase_calls = []

    class Phase:
        name = "phase"

        def on_before_turn(self, flow):
            phase_calls.append(flow.session_id)

    hooks = ToolHookExecutor()
    hooks.register(_PluginToolHook(
        tool_name="echo",
        priority=0,
        plugin_id="demo",
        handler=lambda ctx: HookOutcome(
            decision="modify",
            modified_args={"text": "rewritten"},
        ),
    ))
    registry = ToolRegistry()
    registry.register(_EchoTool())
    agent = _Agent()
    pipeline = PassiveTurnPipeline(
        agent=agent,
        tool_registry=registry,
        phase_modules_provider=lambda: [Phase()],
        tool_hook_executor=hooks,
        enable_thinking=False,
    )

    pipeline.process(InboundMessage(channel="cli", session_id="s1", text="测试"))

    assert phase_calls == ["s1"]
    assert agent.committed == ("测试", "完成")


def test_tool_hook_sync_bridge_works_inside_running_event_loop():
    hooks = ToolHookExecutor()
    hooks.register(_PluginToolHook(
        tool_name="echo",
        priority=0,
        plugin_id="demo",
        handler=lambda ctx: {"text": "rewritten"},
    ))

    async def run():
        return hooks.execute_sync("echo", {"text": "original"})

    outcome = asyncio.run(run())
    assert outcome.modified_args == {"text": "rewritten"}

from application.capabilities.llm.client import LLMResult, LLMToolCall
from application.capabilities.tools.base import ToolResult
from application.capabilities.tools.registry import ToolRegistry
from application.passive.app.phase import TurnFlow
from application.passive.app.reasoning import PassiveReasoner
from infra.config import AppConfig


class _EchoTool:
    name = "echo"
    description = "回显文本"
    input_schema = {"type": "object"}

    def run(self, tool_input: dict[str, str]) -> ToolResult:
        return ToolResult(ok=True, content=tool_input.get("text", ""))


class _Agent:
    def __init__(self) -> None:
        self.tool_options: list[object] = []

    def generate_from_messages(self, messages, *, tools=None):
        self.tool_options.append(tools)
        if tools:
            return LLMResult(
                content="",
                tool_calls=[
                    LLMToolCall(
                        id="call-1",
                        name="echo",
                        arguments_json='{"text":"done"}',
                        arguments={"text": "done"},
                    )
                ],
            )
        return LLMResult(content="已根据已有结果完成。")


def test_default_tool_step_limit_is_twelve():
    config = AppConfig.model_validate(
        {"llm": {"main": {"model": "main", "api_key": "secret"}}}
    )

    assert config.tooling.max_tool_steps == 12


def test_reasoner_requests_a_final_answer_when_tool_limit_is_reached():
    agent = _Agent()
    registry = ToolRegistry()
    registry.register(_EchoTool())
    flow = TurnFlow(
        user_input="执行任务",
        session_id="telegram:1",
        channel="telegram",
        trace_id="trace-1",
        messages=[{"role": "user", "content": "执行任务"}],
        tools=[{"type": "function", "function": {"name": "echo"}}],
    )

    result = PassiveReasoner(
        agent=agent,
        tool_registry=registry,
        max_tool_steps=1,
    ).run_sync(flow)

    assert result.final_output == "已根据已有结果完成。"
    assert agent.tool_options == [flow.tools, None]

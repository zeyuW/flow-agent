import asyncio

from application.capabilities.llm.client import LLMResult
from application.delegation.app.sub_agent import SubAgent


def test_subagent_logs_each_step_duration(caplog):
    class ImmediateLLM:
        def generate(self, messages, tools=None):
            del messages, tools
            return LLMResult(content="完成")

    agent = SubAgent(
        system_prompt="research",
        max_iterations=10,
        llm_client=ImmediateLLM(),
    )

    with caplog.at_level("INFO"):
        result = asyncio.run(agent.run("读取项目"))

    assert result == "完成"
    assert any("[subagent] step=1/10 elapsed=" in record.message for record in caplog.records)

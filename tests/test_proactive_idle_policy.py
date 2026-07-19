import asyncio
import json
import time

from flow_agent.proactive.data_gateway import DataGateway
from flow_agent.proactive.gate import AnyActionGate, ProactiveStateStore, check_gate
from flow_agent.proactive.models import DataItem, GatewayResult
from flow_agent.proactive.judge_loop import JudgeLoop
from flow_agent.llm.client import LLMToolCall
from flow_agent.proactive.proactive_pipeline import ProactiveTurnPipeline
from flow_agent.proactive.tools import (
    ConfigureProactivePolicyTool,
    GetProactiveStatusTool,
)


class _NewsPool:
    async def call(self, server, tool, params=None):
        assert server == "ai-news"
        assert tool == "get_ai_news"
        return json.dumps(
            {
                "count": 1,
                "items": [
                    {
                        "title": "新的 Agent 模型发布",
                        "url": "https://example.com/agent",
                        "summary": "模型增加了工具调用能力",
                        "source": "Example News",
                    }
                ],
                "provider_errors": [],
            },
            ensure_ascii=False,
        )


class _SourceSpec:
    channels = ("content",)
    server = "ai-news"
    fetch_tool = "get_ai_news"
    ack_tool = None


class _RegisteredSource:
    spec = _SourceSpec()
    source_key = "builtin:ai-news"


class _EmptyGateway:
    async def run(self):
        return GatewayResult()


class _FailedGateway:
    async def run(self):
        return GatewayResult(errors=["mcp:ai-news/get_ai_news: timeout"])


class _UnusedJudge:
    async def evaluate(self, gateway, chat_id="", *, policy_topics=()):
        raise AssertionError("空数据进入 Drift 时不应调用 Judge")


class _EmptyDrift:
    async def run(self, connected_mcp):
        from flow_agent.proactive.drift_models import DriftTick

        return DriftTick()


def test_policy_tool_persists_and_gate_waits_for_idle(tmp_path):
    path = tmp_path / "proactive.db"
    store = ProactiveStateStore(path)
    configure = ConfigureProactivePolicyTool(store)
    result = configure.run(
        {
            "__chat_id": "chat-1",
            "idle_minutes": 30,
            "topics": ["AI", "编程", "AI"],
        }
    )
    assert result.ok is True
    now = time.time()
    store.record_user_interaction("chat-1", now)

    waiting = check_gate(
        chat_id="chat-1",
        state_store=store,
        any_action=AnyActionGate(max_per_day=10),
        cooldown=0,
        now=now + 29 * 60,
    )
    assert waiting.passed is False
    assert waiting.reason == "idle_wait"

    ready = check_gate(
        chat_id="chat-1",
        state_store=store,
        any_action=AnyActionGate(max_per_day=10),
        cooldown=0,
        now=now + 31 * 60,
    )
    assert ready.passed is True
    store.close()

    restored = ProactiveStateStore(path)
    policy = restored.get_policy("chat-1")
    assert policy.enabled is True
    assert policy.idle_threshold_seconds == 1800
    assert policy.topics == ("AI", "编程")
    status = GetProactiveStatusTool(restored).run({"__chat_id": "chat-1"})
    assert status.ok is True
    assert json.loads(status.content)["topics"] == ["AI", "编程"]
    restored.close()


def test_builtin_news_payload_expands_into_content_item():
    gateway = DataGateway(_NewsPool(), [_RegisteredSource()])
    result = asyncio.run(gateway.run())

    assert len(result.content) == 1
    item = result.content[0]
    assert item.item_id == "https://example.com/agent"
    assert item.source == "Example News"
    assert "https://example.com/agent" in item.content


def test_empty_drift_does_not_consume_cooldown():
    store = ProactiveStateStore()
    pipeline = ProactiveTurnPipeline(
        state_store=store,
        gateway=_EmptyGateway(),
        judge=_UnusedJudge(),
        any_action=AnyActionGate(max_per_day=10),
        cooldown=0,
        drift_pipeline=_EmptyDrift(),
        drift_enabled=True,
        drift_min_interval_hours=24,
    )

    tick = asyncio.run(pipeline.run(chat_id="chat-1"))

    assert tick.drift_tick is not None
    assert store.get_drift_last_at() == 0


def test_source_failure_does_not_enter_drift():
    store = ProactiveStateStore()
    pipeline = ProactiveTurnPipeline(
        state_store=store,
        gateway=_FailedGateway(),
        judge=_UnusedJudge(),
        any_action=AnyActionGate(max_per_day=10),
        cooldown=0,
        drift_pipeline=_EmptyDrift(),
        drift_enabled=True,
        drift_min_interval_hours=0,
    )

    tick = asyncio.run(pipeline.run(chat_id="chat-1"))

    assert tick.drift_tick is None
    assert tick.judge_result.decision == "skip"
    assert tick.judge_result.evidence["reason"] == "source_error"


def test_judge_limits_memory_recall_and_falls_back_to_explicit_topics():
    class RepeatingRecallLLM:
        def __init__(self):
            self.tool_names = []

        def generate(self, messages, tools=None):
            self.tool_names.append(
                [item["function"]["name"] for item in tools or []]
            )
            return type(
                "Response",
                (),
                {
                    "content": "",
                    "tool_calls": [
                        LLMToolCall(
                            id="call-recall",
                            name="recall_memory",
                            arguments={"query": "用户兴趣"},
                            arguments_json='{"query":"用户兴趣"}',
                        )
                    ],
                },
            )()

    llm = RepeatingRecallLLM()
    judge = JudgeLoop(llm_client=llm, max_steps=2)
    gateway = GatewayResult(
        content=[
            DataItem(
                source="news",
                item_id="news-1",
                title="新的 AI Agent 发布",
                summary="新增了工具调用能力",
                content="新增了工具调用能力\nhttps://example.com/news-1",
            )
        ]
    )

    result = asyncio.run(
        judge.evaluate(gateway, "chat-1", policy_topics=("AI",))
    )

    assert "recall_memory" in llm.tool_names[0]
    assert "recall_memory" not in llm.tool_names[1]
    assert result.decision == "reply"
    assert result.cited_item_ids == ["news-1"]
    assert "https://example.com/news-1" in result.message


def test_judge_respects_explicit_skip_even_with_policy_topics():
    class SkipLLM:
        def generate(self, messages, tools=None):
            return type(
                "Response",
                (),
                {
                    "content": "",
                    "tool_calls": [
                        LLMToolCall(
                            id="call-skip",
                            name="finish_turn",
                            arguments={"decision": "skip"},
                            arguments_json='{"decision":"skip"}',
                        )
                    ],
                },
            )()

    judge = JudgeLoop(llm_client=SkipLLM(), max_steps=2)
    gateway = GatewayResult(
        content=[
            DataItem(
                source="news",
                item_id="news-1",
                title="普通更新",
                summary="没有新的有效信息",
                content="没有新的有效信息",
            )
        ]
    )

    result = asyncio.run(
        judge.evaluate(gateway, "chat-1", policy_topics=("AI",))
    )

    assert result.decision == "skip"
    assert result.message == ""


def test_judge_rejects_reply_without_message_draft():
    class ReplyWithoutDraftLLM:
        def __init__(self):
            self.calls = 0

        def generate(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return type("Response", (), {
                    "content": "",
                    "tool_calls": [LLMToolCall(
                        id="finish-empty",
                        name="finish_turn",
                        arguments={"decision": "reply"},
                        arguments_json='{"decision":"reply"}',
                    )],
                })()
            assert "不能在没有 message_push 草稿时完成 reply" in messages[-1]["content"]
            return type("Response", (), {
                "content": "",
                "tool_calls": [
                    LLMToolCall(
                        id="push-1",
                        name="message_push",
                        arguments={"text": "一条真实候选消息"},
                        arguments_json='{"text":"一条真实候选消息"}',
                    ),
                    LLMToolCall(
                        id="finish-1",
                        name="finish_turn",
                        arguments={"decision": "reply"},
                        arguments_json='{"decision":"reply"}',
                    ),
                ],
            })()

    judge = JudgeLoop(llm_client=ReplyWithoutDraftLLM(), max_steps=2)
    gateway = GatewayResult(content=[DataItem(
        source="news",
        item_id="news-1",
        title="AI 更新",
        summary="真实摘要",
        content="真实摘要",
    )])

    result = asyncio.run(judge.evaluate(gateway, "chat-1"))

    assert result.decision == "reply"
    assert result.message == "一条真实候选消息"

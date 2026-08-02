"""Tests for the new ProactiveTurnPipeline (Gate + Fetch + Judge + Resolve + Deliver)."""

from pathlib import Path

from modules.capabilities.llm.client import LLMResult, LLMToolCall
from modules.memory.markdown_store import MarkdownStore
from modules.proactive.infra.gate import ProactiveStateStore, AnyActionGate, check_gate
from modules.proactive.domain.models import (
    AgentTick, GateResult, GatewayResult, DataItem,
    JudgeResult, ResolveResult, DeliverResult,
)
from modules.proactive.application.resolve import resolve_decision
from modules.proactive.application.pipeline import ProactiveTurnPipeline
from modules.proactive.infra.data_gateway import DataGateway
from modules.proactive.application.judge_loop import JudgeLoop
from modules.proactive.infra.mcp_pool import McpClientPool
from modules.proactive.application.deliver import deliver_message


# ── fake helpers ──

class _FakeLLM:
    """Fake LLM that skips (no tool_calls)."""

    def generate(self, messages, tools=None):
        class _Resp:
            content = ""
            tool_calls = []
        return _Resp()


def _build_pipeline(store, any_action, cooldown=0.0):
    pool = McpClientPool()
    gateway = DataGateway(pool)
    judge = JudgeLoop(llm_client=_FakeLLM())
    return ProactiveTurnPipeline(
        state_store=store,
        gateway=gateway,
        judge=judge,
        any_action=any_action,
        cooldown=cooldown,
    )


# ── tests ──

def test_gate_blocks_when_no_chat_id():
    result = check_gate(chat_id="", is_busy=False)
    assert result.passed is False
    assert result.reason == "no_target"


def test_gate_passes_when_all_clear():
    store = ProactiveStateStore()
    any_action = AnyActionGate(max_per_day=100)
    result = check_gate(
        chat_id="test_chat",
        state_store=store,
        any_action=any_action,
        base_score=0.5,
    )
    assert result.passed is True


def test_pipeline_run_blocked_by_gate():
    store = ProactiveStateStore()
    any_action = AnyActionGate(max_per_day=100)
    pipeline = _build_pipeline(store, any_action)

    import asyncio
    tick = asyncio.run(pipeline.run(chat_id="", base_score=0.5))
    assert isinstance(tick, AgentTick)
    assert tick.gate_result.passed is False


def test_pipeline_run_passed_gate():
    store = ProactiveStateStore()
    any_action = AnyActionGate(max_per_day=100)
    pipeline = _build_pipeline(store, any_action)

    import asyncio
    tick = asyncio.run(pipeline.run(chat_id="test_chat", base_score=0.9))
    assert tick.gate_result.passed is True
    # DataGateway returns empty results (no MCP servers configured)
    assert tick.gateway_result is not None
    assert tick.gateway_result.alerts == []


def test_resolve_skip_when_judge_says_skip():
    store = ProactiveStateStore()
    judge = JudgeResult(decision="skip", message="nothing interesting")
    result = resolve_decision(judge, state_store=store)
    assert result.decision == "skip"


def test_resolve_skip_on_dedup():
    store = ProactiveStateStore()
    # Use the same cited_item_ids that resolve_decision will compute the key from
    cited = ["item_xyz"]
    import hashlib
    # _build_delivery_key sorts and hashes: hashlib.sha256(",".join(sorted(cited)).encode()).hexdigest()[:24]
    actual_key = hashlib.sha256(",".join(sorted(cited)).encode()).hexdigest()[:24]
    store.mark_sent(actual_key)
    judge = JudgeResult(
        decision="reply",
        message="repeated message",
        cited_item_ids=cited,
    )
    result = resolve_decision(judge, state_store=store)
    assert result.decision == "skip"


def test_resolve_send_when_no_dedup():
    store = ProactiveStateStore()
    judge = JudgeResult(
        decision="reply",
        message="fresh news",
        cited_item_ids=["new_item_123"],
    )
    result = resolve_decision(judge, state_store=store)
    assert result.decision == "send"
    assert result.message == "fresh news"


def test_deliver_sets_sent_flag():
    class DeliveredPort:
        async def send_and_wait(self, dispatch, timeout=30.0):
            del dispatch, timeout
            return type("Receipt", (), {"delivered": True, "error": ""})()

    resolve = ResolveResult(
        decision="send",
        message="hello",
        cited_item_ids=["id1"],
        delivery_key="key1",
    )
    import asyncio
    result = asyncio.run(
        deliver_message(resolve, chat_id="test", outbound_port=DeliveredPort())
    )
    assert isinstance(result, DeliverResult)
    assert result.sent is True


def test_deliver_skip_when_not_send():
    resolve = ResolveResult(decision="skip", message="")
    import asyncio
    result = asyncio.run(deliver_message(resolve, chat_id="test"))
    assert result.sent is False


def test_state_store_maintains_counts():
    store = ProactiveStateStore()
    assert store.daily_count == 0
    store.mark_sent("k1")
    assert store.daily_count == 1
    store.mark_sent("k2")
    assert store.daily_count == 2


def test_judge_injects_shared_markdown_memory(tmp_path: Path):
    markdown = MarkdownStore(tmp_path / "memory")
    markdown.initialize()
    markdown.append_memory_item("preference", "用户不喜欢悬疑压抑风格")
    markdown.update_recent_compression("- 用户最近在挑选轻松的游戏")

    class CapturingLLM:
        def __init__(self):
            self.messages = []

        def generate(self, messages, tools=None):
            self.messages = messages
            return LLMResult(content="", tool_calls=[])

    llm = CapturingLLM()
    judge = JudgeLoop(llm_client=llm, markdown_store=markdown, max_steps=1)
    gateway = GatewayResult(content=[
        DataItem(source="feed", item_id="game-1", title="新游戏", summary="一款新作"),
    ])

    import asyncio
    asyncio.run(judge.evaluate(gateway))

    rendered = "\n".join(str(message.get("content", "")) for message in llm.messages)
    assert "用户不喜欢悬疑压抑风格" in rendered
    assert "用户最近在挑选轻松的游戏" in rendered
    assert "待归档用户画像" not in rendered


def test_judge_returns_recall_result_to_model():
    class StubMemory:
        def retrieve_for_prompt(self, query):
            assert query == "用户对 Rust 的兴趣"
            return "用户长期关注 Rust"

    class SequencedLLM:
        def __init__(self):
            self.calls = []

        def generate(self, messages, tools=None):
            self.calls.append(messages)
            if len(self.calls) == 1:
                return LLMResult(content="", tool_calls=[LLMToolCall(
                    id="recall-1",
                    name="recall_memory",
                    arguments_json='{"query":"用户对 Rust 的兴趣"}',
                    arguments={"query": "用户对 Rust 的兴趣"},
                )])
            tool_messages = [message for message in messages if message.get("role") == "tool"]
            assert tool_messages[-1]["content"] == "用户长期关注 Rust"
            return LLMResult(content="", tool_calls=[
                LLMToolCall(
                    id="mark-1",
                    name="mark_interesting",
                    arguments_json='{"item_id":"rust-1","reason":"匹配长期兴趣"}',
                    arguments={"item_id": "rust-1", "reason": "匹配长期兴趣"},
                ),
                LLMToolCall(
                    id="push-1",
                    name="message_push",
                    arguments_json='{"text":"Rust 有一条值得关注的新动态。"}',
                    arguments={"text": "Rust 有一条值得关注的新动态。"},
                ),
                LLMToolCall(
                    id="finish-1",
                    name="finish_turn",
                    arguments_json='{"decision":"reply"}',
                    arguments={"decision": "reply"},
                ),
            ])

    llm = SequencedLLM()
    judge = JudgeLoop(llm_client=llm, memory_engine=StubMemory(), max_steps=3)
    gateway = GatewayResult(content=[
        DataItem(source="feed", item_id="rust-1", title="Rust 更新", summary="工具链更新"),
    ])

    import asyncio
    result = asyncio.run(judge.evaluate(gateway))

    assert len(llm.calls) == 2
    assert result.decision == "reply"
    assert result.message == "Rust 有一条值得关注的新动态。"
    assert result.cited_item_ids == ["rust-1"]

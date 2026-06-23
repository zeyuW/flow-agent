"""Tests for the new ProactiveTurnPipeline (Gate + Fetch + Judge + Resolve + Deliver)."""

from pathlib import Path

from flow_agent.proactive.gate import ProactiveStateStore, AnyActionGate, check_gate
from flow_agent.proactive.models import (
    AgentTick, GateResult, GatewayResult, DataItem,
    JudgeResult, ResolveResult, DeliverResult,
)
from flow_agent.proactive.resolve import resolve_decision
from flow_agent.proactive.proactive_pipeline import ProactiveTurnPipeline
from flow_agent.proactive.data_gateway import DataGateway
from flow_agent.proactive.judge_loop import JudgeLoop
from flow_agent.proactive.mcp_pool import McpClientPool
from flow_agent.proactive.deliver import deliver_message


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
    resolve = ResolveResult(
        decision="send",
        message="hello",
        cited_item_ids=["id1"],
        delivery_key="key1",
    )
    import asyncio
    result = asyncio.run(deliver_message(resolve, chat_id="test"))
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

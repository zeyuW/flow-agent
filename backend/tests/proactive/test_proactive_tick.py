"""Tests for the new ProactiveTurnPipeline (Gate + Fetch + Judge + Resolve + Deliver)."""

from pathlib import Path

from application.capabilities.llm.client import LLMResult, LLMToolCall
from application.memory.infra.markdown_store import MarkdownStore
from application.proactive.infra.gate import ProactiveStateStore, AnyActionGate, check_gate
from application.proactive.domain.models import (
    AgentTick, GateResult, GatewayResult, DataItem,
    JudgeResult, ResolveResult, DeliverResult,
)
from application.proactive.app.resolve import resolve_decision
from application.proactive.app.pipeline import ProactiveTurnPipeline
from application.proactive.infra.data_gateway import DataGateway
from application.proactive.app.judge_loop import JudgeLoop
from application.proactive.infra.mcp_pool import McpClientPool
from application.proactive.app.deliver import deliver_message


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


class _StaticGateway:
    def __init__(self, result: GatewayResult):
        self.result = result

    async def run(self) -> GatewayResult:
        return self.result


class _RecordingJudge:
    def __init__(self, result: JudgeResult | None = None):
        self.calls: list[list[DataItem]] = []
        self.result = result or JudgeResult(decision="skip")

    async def evaluate(self, gateway: GatewayResult, *args, **kwargs) -> JudgeResult:
        del args, kwargs
        self.calls.append(list(gateway.all_items))
        return self.result


def _build_stateful_pipeline(store, gateway, judge):
    return ProactiveTurnPipeline(
        state_store=store,
        gateway=gateway,
        judge=judge,
        any_action=AnyActionGate(max_per_day=100),
        cooldown=0.0,
    )


def test_first_startup_fetch_establishes_baseline_without_judging(tmp_path: Path):
    """首次启动只记录已有候选，不应把历史内容当成新内容推送。"""

    store = ProactiveStateStore(tmp_path / "proactive.db")
    judge = _RecordingJudge()
    gateway = _StaticGateway(
        GatewayResult(content=[
            DataItem(
                source="feed",
                source_key="feed:tech",
                item_id="old-1",
                title="启动前已存在的内容",
            ),
        ])
    )
    pipeline = _build_stateful_pipeline(store, gateway, judge)

    import asyncio
    tick = asyncio.run(pipeline.run(chat_id="target"))

    assert tick.judge_result is not None
    assert tick.judge_result.decision == "skip"
    assert tick.judge_result.evidence["reason"] == "startup_baseline"
    assert judge.calls == []
    store.close()


def test_restart_does_not_rejudge_seen_candidate(tmp_path: Path):
    """重启后仍存在的数据源内容不能再次进入 Judge。"""

    state_path = tmp_path / "proactive.db"
    gateway = _StaticGateway(
        GatewayResult(content=[
            DataItem(
                source="feed",
                source_key="feed:tech",
                item_id="old-1",
                title="已经观察过的内容",
            ),
        ])
    )

    first = ProactiveStateStore(state_path)
    first_pipeline = _build_stateful_pipeline(first, gateway, _RecordingJudge())
    import asyncio
    asyncio.run(first_pipeline.run(chat_id="target"))
    first.close()

    second = ProactiveStateStore(state_path)
    judge = _RecordingJudge()
    second_pipeline = _build_stateful_pipeline(second, gateway, judge)
    tick = asyncio.run(second_pipeline.run(chat_id="target"))

    assert tick.judge_result is not None
    assert tick.judge_result.evidence["reason"] == "no_new_candidates"
    assert judge.calls == []
    second.close()


def test_new_candidate_after_baseline_is_sent_to_judge(tmp_path: Path):
    """建立基线后出现的新候选仍必须进入评估流程。"""

    store = ProactiveStateStore(tmp_path / "proactive.db")
    old_item = DataItem(
        source="feed",
        source_key="feed:tech",
        item_id="old-1",
        title="旧内容",
    )
    gateway = _StaticGateway(GatewayResult(content=[old_item]))
    asyncio_run = __import__("asyncio").run
    asyncio_run(_build_stateful_pipeline(store, gateway, _RecordingJudge()).run(
        chat_id="target"
    ))

    new_item = DataItem(
        source="feed",
        source_key="feed:tech",
        item_id="new-1",
        title="新内容",
    )
    gateway.result = GatewayResult(content=[old_item, new_item])
    judge = _RecordingJudge()
    tick = asyncio_run(_build_stateful_pipeline(store, gateway, judge).run(
        chat_id="target"
    ))

    assert tick.judge_result is not None
    assert len(judge.calls) == 1
    assert [item.item_id for item in judge.calls[0]] == ["new-1"]
    store.close()


def test_duplicate_candidate_in_one_fetch_is_judged_once(tmp_path: Path):
    """同一轮多个通道返回相同候选时只能评估一次。"""

    store = ProactiveStateStore(tmp_path / "proactive.db")
    old_item = DataItem(
        source="feed",
        source_key="feed:tech",
        item_id="old-1",
        title="旧内容",
    )
    new_item = DataItem(
        source="feed",
        source_key="feed:tech",
        item_id="new-1",
        title="新内容",
    )
    gateway = _StaticGateway(GatewayResult(content=[old_item]))
    import asyncio
    asyncio.run(_build_stateful_pipeline(store, gateway, _RecordingJudge()).run(
        chat_id="target"
    ))

    gateway.result = GatewayResult(content=[new_item, new_item])
    judge = _RecordingJudge()
    asyncio.run(_build_stateful_pipeline(store, gateway, judge).run(
        chat_id="target"
    ))

    assert len(judge.calls) == 1
    assert [item.item_id for item in judge.calls[0]] == ["new-1"]
    store.close()


def test_delivery_failure_keeps_candidate_for_retry(tmp_path: Path):
    """首次投递失败时不应消耗候选，下一轮仍需重新评估并发送。"""

    store = ProactiveStateStore(tmp_path / "proactive.db")
    old_item = DataItem(
        source="feed",
        source_key="feed:tech",
        item_id="old-1",
        title="旧内容",
    )
    new_item = DataItem(
        source="feed",
        source_key="feed:tech",
        item_id="new-1",
        title="新内容",
    )
    gateway = _StaticGateway(GatewayResult(content=[old_item]))
    import asyncio
    asyncio.run(_build_stateful_pipeline(store, gateway, _RecordingJudge()).run(
        chat_id="target"
    ))

    gateway.result = GatewayResult(content=[new_item])
    judge = _RecordingJudge(
        JudgeResult(
            decision="reply",
            message="新内容提醒",
            cited_item_ids=["new-1"],
        )
    )

    class Sender:
        def __init__(self):
            self.calls = 0

        async def send_and_wait(self, message, timeout=30.0):
            del message, timeout
            self.calls += 1
            return type(
                "Result",
                (),
                {
                    "accepted": self.calls > 1,
                    "error": "temporary failure" if self.calls == 1 else "",
                },
            )()

    sender = Sender()
    first_pipeline = ProactiveTurnPipeline(
        state_store=store,
        gateway=gateway,
        judge=judge,
        any_action=AnyActionGate(max_per_day=100),
        cooldown=0.0,
        message_sender=sender,
    )
    first = asyncio.run(first_pipeline.run(chat_id="target"))
    second = asyncio.run(first_pipeline.run(chat_id="target"))

    assert first.sent is False
    assert second.sent is True
    assert sender.calls == 2
    assert len(judge.calls) == 2
    store.close()

from pathlib import Path
from types import SimpleNamespace

from application.conversation.app.pipeline import PassiveTurnPipeline
from application.conversation.app.phase import TurnFlow
from application.capabilities.tools.guard import ToolGuard
from application.capabilities.llm.client import LLMResult, LLMToolCall
from application.memory.markdown_store import MarkdownStore
from application.memory.memory_engine import MemoryEngine
from application.memory.app.memorizer import Memorizer
from application.memory.app.post_response import PostResponseContext, PostResponseMemoryWorker
from application.memory.infra.vector_store import MemoryStore
from application.memory.app.memorize import MemorizeTool, MemorizeToolAdapter
from application.capabilities.tools.registry import ToolRegistry


class FixedEmbedder:
    @property
    def dimension(self) -> int:
        return 8

    def embed(self, text: str) -> list[float]:
        seed = sum(text.encode("utf-8"))
        return [((seed + idx) % 17) / 17 for idx in range(self.dimension)]


def _build_worker(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory_vectors.db", vec_dim=8)
    embedder = FixedEmbedder()
    memorizer = Memorizer(store=store, embedder=embedder)
    markdown = MarkdownStore(tmp_path / "memory")
    markdown.initialize()
    worker = PostResponseMemoryWorker(
        store=store,
        memorizer=memorizer,
        markdown_store=markdown,
    )
    return store, markdown, worker


def test_post_response_only_writes_immediate_procedure(tmp_path: Path):
    store, markdown, worker = _build_worker(tmp_path)

    result = worker.process(
        PostResponseContext(
            session_id="s1",
            user_input=(
                "规则：回复必须使用中文。"
                "偏好：我喜欢中文回复。"
                "需求：我需要长期记住项目规则。"
                "任务：帮我实现记忆写入"
            ),
            assistant_output="好的",
        )
    )

    assert result.extracted_memories == 1
    by_type = {item.memory_type: item.summary for item in store.list_active()}
    assert set(by_type) == {"procedure"}
    assert by_type["procedure"] == "用户规则：回复必须使用中文"

    memory_text = markdown.read_memory()
    pending_text = markdown.read_pending()
    assert "用户规则：回复必须使用中文" in memory_text
    assert "用户喜欢中文回复" not in memory_text
    assert "用户需要长期记住项目规则" not in pending_text


def test_post_response_defers_profile_facts_to_consolidation(tmp_path: Path):
    _store, markdown, worker = _build_worker(tmp_path)

    worker.process(
        PostResponseContext(
            session_id="s1",
            user_input="我叫小明，以后请称呼我小明。",
            assistant_output="好的",
        )
    )

    memory_text = markdown.read_memory()
    assert "用户叫小明" not in memory_text
    assert "用户叫小明" not in markdown.read_pending()


def test_markdown_store_migrates_existing_memory_template(tmp_path: Path):
    markdown = MarkdownStore(tmp_path / "memory")
    markdown.root.mkdir(parents=True)
    markdown.memory_file.write_text(
        """# 用户记忆档案

> 最后更新：2026-07-15 17:46 UTC

## 身份信息 (Identity)
<!-- 用户的基本身份信息 -->

## 偏好设置 (Preferences)
<!-- 用户的使用偏好 -->

## 目标与计划 (Goals)
<!-- 用户的目标和计划 -->

## 约束限制 (Constraints)
<!-- 用户的行为约束和限制 -->
""",
        encoding="utf-8",
    )

    markdown.initialize()

    content = markdown.read_memory()
    assert "## 事实信息" in content
    assert "## 需求记录" in content
    assert content.index("## 身份信息") < content.index("## 事实信息")
    assert content.index("## 偏好设置") < content.index("## 需求记录")


def test_memorizer_hash_separates_same_text_by_memory_type(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory_vectors.db", vec_dim=8)
    memorizer = Memorizer(store=store, embedder=FixedEmbedder())

    fact = memorizer.memorize("fact", "用户喜欢中文")
    preference = memorizer.memorize("preference", "用户喜欢中文")

    assert fact.content_hash != preference.content_hash
    assert store.count_active() == 2


def test_memorize_tool_adapter_runs_through_registry(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory_vectors.db", vec_dim=8)
    memorizer = Memorizer(store=store, embedder=FixedEmbedder())
    registry = ToolRegistry()
    registry.set_guard(ToolGuard(whitelist={"memorize"}))
    registry.register(MemorizeToolAdapter(MemorizeTool(memorizer=memorizer, store=store)))

    result = registry.execute(
        "memorize",
        {
            "memory_type": "need",
            "summary": "用户需要代理主动写入事实和偏好",
        },
    )

    assert result.ok is True
    items = store.list_active("need")
    assert len(items) == 1
    assert items[0].summary == "用户需要代理主动写入事实和偏好"


def test_memorize_tool_syncs_explicit_write_to_markdown(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory_vectors.db", vec_dim=8)
    markdown = MarkdownStore(tmp_path / "memory")
    markdown.initialize()
    tool = MemorizeTool(
        memorizer=Memorizer(store=store, embedder=FixedEmbedder()),
        store=store,
        markdown_store=markdown,
    )

    tool('{"memory_type": "preference", "summary": "用户偏好中文回复"}')

    assert "用户偏好中文回复" in markdown.read_memory()


def test_passive_pipeline_injects_long_term_memory_before_recent_history():
    class StubMemoryEngine:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        def retrieve_for_prompt(self, query: str, max_items: int) -> str:
            self.calls.append((query, max_items))
            return "[流程规范 - 用户偏好与规则]\n- 用户偏好中文回复"

    agent = SimpleNamespace(
        context=SimpleNamespace(
            get_history=lambda _session_id: [
                {"role": "user", "content": "上一轮消息"},
            ]
        )
    )
    engine = StubMemoryEngine()
    pipeline = PassiveTurnPipeline(
        agent=agent,
        tool_registry=ToolRegistry(),
        memory_engine=engine,
        retrieval_max_items=4,
    )

    block = pipeline._build_memory_block("s1", "请按我的偏好回复")

    assert engine.calls == [("请按我的偏好回复", 4)]
    assert block.index("用户偏好中文回复") < block.index("近期对话回顾")


def test_streaming_pipeline_reuses_rendered_memory_messages():
    class StreamClient:
        def __init__(self) -> None:
            self.messages: list[dict[str, str]] = []

        def generate_stream(self, messages, tools, on_delta):
            self.messages = messages
            on_delta("回复中")
            return SimpleNamespace(content="完成")

    class EventBus:
        def __init__(self) -> None:
            self.events: list[object] = []

        def publish(self, event) -> None:
            self.events.append(event)

    stream_client = StreamClient()
    agent = SimpleNamespace(llm_client=stream_client)
    pipeline = PassiveTurnPipeline(
        agent=agent,
        tool_registry=ToolRegistry(),
        event_bus=EventBus(),
        enable_thinking=True,
    )
    flow = TurnFlow(
        user_input="请按偏好回复",
        session_id="s1",
        channel="telegram",
        inbound_metadata={"telegram_chat_id": "42"},
        trace_id="trace-1",
    )
    flow.messages = [{"role": "system", "content": "用户偏好中文回复"}]

    result = pipeline._reasoner(flow)

    assert result.final_output == "完成"
    assert stream_client.messages == flow.messages


def test_streaming_tool_call_continues_in_tool_loop():
    class StreamClient:
        def generate_stream(self, messages, tools, on_delta):
            return LLMResult(content="", tool_calls=[LLMToolCall(
                id="call-1",
                name="lookup",
                arguments_json='{"query":"状态"}',
                arguments={"query": "状态"},
            )])

    class Agent:
        def __init__(self) -> None:
            self.llm_client = StreamClient()
            self.generate_calls = 0

        def generate_from_messages(self, messages, tools=None):
            self.generate_calls += 1
            assert messages[-1]["role"] == "tool"
            assert "查询完成" in messages[-1]["content"]
            return LLMResult(content="最终回复", tool_calls=None)

    class Registry:
        def execute(self, tool_name, tool_input):
            assert tool_name == "lookup"
            assert tool_input == {"query": "状态"}
            return SimpleNamespace(ok=True, content="查询完成")

    agent = Agent()
    pipeline = PassiveTurnPipeline(
        agent=agent,
        tool_registry=Registry(),
        event_bus=SimpleNamespace(publish=lambda _event: None),
        enable_thinking=True,
    )
    flow = TurnFlow(
        user_input="查询状态",
        session_id="s1",
        channel="telegram",
        inbound_metadata={"telegram_chat_id": "42"},
        trace_id="trace-tool",
    )
    flow.messages = [{"role": "user", "content": "查询状态"}]
    flow.tools = [{"type": "function", "function": {"name": "lookup"}}]

    result = pipeline._reasoner(flow)

    assert result.final_output == "最终回复"
    assert agent.generate_calls == 1


def test_after_turn_replaces_empty_model_output():
    committed: list[tuple[str, str]] = []
    sent: list[object] = []
    agent = SimpleNamespace(
        commit_turn=lambda user_input, assistant_output: committed.append(
            (user_input, assistant_output)
        ),
    )
    pipeline = PassiveTurnPipeline(
        agent=agent,
        tool_registry=ToolRegistry(),
        outbound_port=SimpleNamespace(send=sent.append),
    )
    flow = TurnFlow(
        user_input="你好",
        session_id="s1",
        channel="telegram",
        trace_id="trace-empty",
    )
    flow.final_output = ""

    pipeline._after_turn(flow)

    assert flow.final_output == "抱歉，本轮没有生成有效回复，请再试一次。"
    assert committed == [("你好", flow.final_output)]
    assert sent[0].text == flow.final_output


def test_error_reply_keeps_telegram_routing_metadata():
    sent: list[object] = []
    pipeline = PassiveTurnPipeline(
        agent=SimpleNamespace(),
        tool_registry=ToolRegistry(),
        outbound_port=SimpleNamespace(send=sent.append),
    )
    flow = TurnFlow(
        user_input="你好",
        session_id="s1",
        channel="telegram",
        inbound_metadata={"telegram_chat_id": "42"},
        trace_id="trace-error",
    )

    pipeline._send_error_reply(flow, IndexError("测试错误"))

    assert sent[0].metadata["telegram_chat_id"] == "42"
    assert sent[0].metadata["error"] is True


def test_profile_query_can_find_preference_without_profile_type_filter(tmp_path: Path):
    store = MemoryStore(tmp_path / "memory_vectors.db", vec_dim=8)
    embedder = FixedEmbedder()
    memorizer = Memorizer(store=store, embedder=embedder)
    memorizer.memorize("preference", "用户喜欢中文回复")

    engine = MemoryEngine(store=store, embedder=embedder)
    result = engine.query_text("用户偏好", intent="profile")

    assert any(hit.item.memory_type == "preference" for hit in result.hits)

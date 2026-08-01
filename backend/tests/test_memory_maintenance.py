from pathlib import Path
from types import SimpleNamespace

from flow_agent.memory.maintenance import ConversationConsolidator, MemoryOptimizer
from flow_agent.memory.markdown_store import MarkdownStore
from flow_agent.memory.memorizer import Memorizer
from flow_agent.memory.vector_store import MemoryStore
from flow_agent.session.session_manager import SessionManager
from flow_agent.session.session_store import SessionStore


class FixedEmbedder:
    @property
    def dimension(self) -> int:
        return 8

    def embed(self, text: str) -> list[float]:
        seed = sum(text.encode("utf-8"))
        return [((seed + index) % 17) / 17 for index in range(self.dimension)]


def _build_components(tmp_path: Path):
    sessions = SessionManager(SessionStore(tmp_path / "sessions.db"))
    markdown = MarkdownStore(tmp_path / "memory")
    markdown.initialize()
    vectors = MemoryStore(tmp_path / "memory_vectors.db", vec_dim=8)
    return sessions, markdown, vectors, Memorizer(vectors, FixedEmbedder())


def test_consolidation_persists_window_and_is_idempotent(tmp_path: Path):
    sessions, markdown, vectors, memorizer = _build_components(tmp_path)
    sessions.append_message("chat-1", "user", "我叫小明，我喜欢中文回复。")
    sessions.append_message("chat-1", "assistant", "好的，我会使用中文回复。")
    consolidator = ConversationConsolidator(
        session_manager=sessions,
        markdown_store=markdown,
        memorizer=memorizer,
        llm_client=None,
        min_new_messages=2,
    )

    result = consolidator.on_turn_committed("chat-1")

    assert result.recent_turns_refreshed is True
    assert result.consolidated is True
    assert result.history_count == 1
    assert result.pending_count == 2
    assert result.vector_count == 2
    assert result.compression_updated is True
    assert "我叫小明" in markdown.read_recent_context()
    assert "用户讨论了" in markdown.read_history()
    assert "[identity] 用户叫小明" in markdown.read_pending()
    assert "[preference] 用户喜欢中文回复" in markdown.read_pending()
    assert list(markdown.journal_dir.glob("*.md"))
    assert markdown.consolidation_db.exists()
    assert vectors.count_active() == 2
    assert sessions.get_or_create("chat-1").last_consolidated == 2

    sessions.mark_consolidated(sessions.get_or_create("chat-1"), 0)
    retry = consolidator.on_turn_committed("chat-1")

    assert retry.reason == "消息窗口已经归档"
    assert markdown.read_history().count("用户讨论了") == 1
    assert vectors.count_active() == 2
    assert sessions.get_or_create("chat-1").last_consolidated == 2


def test_optimizer_merges_snapshot_into_memory_and_self(tmp_path: Path):
    _sessions, markdown, _vectors, _memorizer = _build_components(tmp_path)
    markdown.append_pending_item("identity", "用户叫小明", "test:identity")
    markdown.append_pending_item("preference", "用户喜欢中文回复", "test:preference")
    markdown.append_pending_item(
        "requested_memory",
        "项目截止日期是 6 月 15 日",
        "test:request",
    )

    result = MemoryOptimizer(markdown).run_once()

    assert result.updated is True
    assert result.merged_count == 3
    memory = markdown.read_memory()
    identity = memory[memory.index("## 身份信息"):memory.index("## 事实信息")]
    preference = memory[memory.index("## 偏好设置"):memory.index("## 需求记录")]
    assert "用户叫小明" in identity
    assert "用户喜欢中文回复" in preference
    assert "项目截止日期是 6 月 15 日" in memory
    assert "用户明确希望助手记住：项目截止日期是 6 月 15 日" in markdown.read_self()
    assert "[identity] 用户叫小明" not in markdown.read_pending()
    assert not markdown.pending_snapshot_file.exists()


def test_markdown_prompt_memory_excludes_pending_and_recent_turns(tmp_path: Path):
    _sessions, markdown, _vectors, _memorizer = _build_components(tmp_path)
    markdown.append_pending_item("preference", "用户喜欢中文回复", "test:pending")
    markdown.refresh_recent_turns([
        {"role": "user", "content": "这是一条临时消息"},
    ])
    markdown.update_recent_compression("- 用户正在讨论记忆归档", "- 继续确认归档策略")

    prompt_memory = markdown.render_prompt_memory()

    assert "用户正在讨论记忆归档" in prompt_memory
    assert "继续确认归档策略" in prompt_memory
    assert "用户喜欢中文回复" not in prompt_memory
    assert "这是一条临时消息" not in prompt_memory


def test_consolidation_preserves_pending_tag_semantics_in_vectors(tmp_path: Path):
    sessions, markdown, vectors, memorizer = _build_components(tmp_path)
    sessions.append_message("chat-1", "user", "请更正我的账号和健康信息。")
    sessions.append_message("chat-1", "assistant", "好的。")

    class TaggedLLM:
        def generate(self, messages):
            prompt = str(messages[0]["content"])
            if "history_entries" in prompt:
                return SimpleNamespace(content='''{
                    "history_entries": [],
                    "pending_items": [
                        {"tag": "key_info", "content": "用户账号是 roco"},
                        {"tag": "health_long_term", "content": "用户有长期偏头痛"},
                        {"tag": "correction", "content": "用户已经毕业，不是学生"}
                    ]
                }''')
            return SimpleNamespace(content='''{
                "compression": "- 用户正在更正长期资料",
                "ongoing_threads": "- 继续核对资料"
            }''')

    consolidator = ConversationConsolidator(
        session_manager=sessions,
        markdown_store=markdown,
        memorizer=memorizer,
        llm_client=TaggedLLM(),
        min_new_messages=2,
    )

    result = consolidator.on_turn_committed("chat-1")

    assert result.vector_count == 3
    assert {item.memory_type for item in vectors.list_active()} == {"fact"}

from flow_agent.memory.retriever import KeywordMemoryRetriever
from flow_agent.memory.store import InMemoryMessageStore


def test_keyword_retriever_returns_relevant_messages():
    store = InMemoryMessageStore()
    store.append_message("s1", "user", "我叫小明")
    store.append_message("s1", "assistant", "你好小明")
    store.append_message("s1", "user", "今天北京天气不错")

    retriever = KeywordMemoryRetriever(store=store)
    results = retriever.retrieve(session_id="s1", query="我叫什么", max_items=5)

    assert results
    assert any("小明" in r.content for r in results)


def test_keyword_retriever_dedupes_same_content():
    store = InMemoryMessageStore()
    store.append_message("s2", "user", "今天要开会")
    store.append_message("s2", "assistant", "今天要开会")
    retriever = KeywordMemoryRetriever(store=store)
    results = retriever.retrieve(session_id="s2", query="今天开会吗", max_items=5)
    assert len(results) == 1


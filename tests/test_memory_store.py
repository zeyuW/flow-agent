from flow_agent.memory.store import InMemoryMessageStore, SQLiteMessageStore


def test_in_memory_message_store_append_and_list():
    store = InMemoryMessageStore()
    store.append_message("s1", "user", "hello")
    store.append_message("s1", "assistant", "hi")

    assert store.list_messages("s1") == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]


def test_in_memory_message_store_returns_copy():
    store = InMemoryMessageStore()
    store.append_message("s1", "user", "hello")

    messages = store.list_messages("s1")
    messages.append({"role": "assistant", "content": "tamper"})

    assert store.list_messages("s1") == [{"role": "user", "content": "hello"}]


def test_sqlite_message_store_persists_messages(tmp_path):
    db_path = tmp_path / "memory.db"
    store = SQLiteMessageStore(db_path)
    store.append_message("s1", "user", "hello")
    store.append_message("s1", "assistant", "hi")

    reloaded = SQLiteMessageStore(db_path)
    assert reloaded.list_messages("s1") == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]


def test_sqlite_message_store_session_isolation(tmp_path):
    store = SQLiteMessageStore(tmp_path / "memory.db")
    store.append_message("s1", "user", "a")
    store.append_message("s2", "user", "b")

    assert store.list_messages("s1") == [{"role": "user", "content": "a"}]
    assert store.list_messages("s2") == [{"role": "user", "content": "b"}]


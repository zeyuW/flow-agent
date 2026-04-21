from flow_agent.memory.organizer import SimpleMemoryOrganizer
from flow_agent.memory.store import InMemoryMessageStore


def test_memory_organizer_dedup_and_trim():
    store = InMemoryMessageStore()
    session_id = "s1"
    store.append_message(session_id, "user", "hi")
    store.append_message(session_id, "assistant", "ok")
    store.append_message(session_id, "assistant", "ok")  # duplicate
    store.append_message(session_id, "assistant", "我无法长期存储个人信息")  # noise
    store.append_message(session_id, "user", "x")
    store.append_message(session_id, "user", "y")

    organizer = SimpleMemoryOrganizer(store=store, max_messages=3, dedupe=True)
    stats = organizer.organize(session_id)

    assert stats["before"] == 6
    assert stats["after"] == 3
    assert store.list_messages(session_id) == [
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": "x"},
        {"role": "user", "content": "y"},
    ]


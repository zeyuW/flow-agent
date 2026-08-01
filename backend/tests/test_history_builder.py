from flow_agent.session.history_builder import get_history
from flow_agent.session.session_models import Session


def test_history_returns_empty_when_cursor_reaches_end():
    session = Session(
        key="s1",
        messages=[
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好"},
        ],
        last_consolidated=2,
    )

    assert get_history(session, start_index=session.last_consolidated) == []


def test_history_aligns_cursor_without_accessing_past_end():
    session = Session(
        key="s1",
        messages=[
            {"role": "user", "content": "第一轮"},
            {"role": "assistant", "content": "第一轮回复"},
            {"role": "user", "content": "第二轮"},
            {"role": "assistant", "content": "第二轮回复"},
        ],
    )

    history = get_history(session, start_index=3)

    assert history == [
        {"role": "user", "content": "第二轮"},
        {"role": "assistant", "content": "第二轮回复"},
    ]

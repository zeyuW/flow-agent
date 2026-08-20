from application.passive.domain.session_key import make_session_key, split_session_key


def test_channel_is_part_of_session_key():
    assert make_session_key("telegram", "123") == "telegram:123"
    assert make_session_key("qq", "123") == "qq:123"


def test_legacy_session_key_is_readable():
    assert split_session_key("123") == ("legacy", "123")


def test_split_keeps_colon_in_external_conversation_id():
    assert split_session_key("qq:group:123") == ("qq", "group:123")


def test_existing_channel_session_key_is_not_prefixed_twice():
    assert make_session_key("qq", "qq:123") == "qq:123"
    assert make_session_key("telegram", "telegram:42") == "telegram:42"

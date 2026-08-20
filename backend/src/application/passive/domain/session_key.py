"""渠道感知的会话键。"""


def make_session_key(channel: str, conversation_id: str) -> str:
    """将渠道和外部会话 ID 组合为内部会话键。"""

    clean_channel = channel.strip().lower()
    if not clean_channel or ":" in clean_channel:
        raise ValueError("渠道名称不能为空且不能包含冒号")
    if conversation_id.startswith(f"{clean_channel}:"):
        return conversation_id
    return f"{clean_channel}:{conversation_id}"


def split_session_key(key: str) -> tuple[str, str]:
    """解析会话键，兼容没有渠道前缀的历史数据。"""

    channel, separator, conversation_id = key.partition(":")
    if not separator or not channel:
        return "legacy", key
    return channel, conversation_id

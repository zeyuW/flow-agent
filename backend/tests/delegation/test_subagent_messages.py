from application.delegation.app.sub_agent import _trim_old_tool_results


def test_trim_old_tool_results_keeps_tool_messages_with_assistant_call():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
    ]
    for index in range(8):
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call-{index}",
                            "type": "function",
                            "function": {"name": "read", "arguments": "{}"},
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": f"call-{index}",
                    "content": f"result-{index}",
                },
            ]
        )

    trimmed = _trim_old_tool_results(messages, keep_recent=5)

    for index, message in enumerate(trimmed):
        if message["role"] == "tool":
            previous = trimmed[index - 1]
            assert previous["role"] == "assistant"
            assert previous.get("tool_calls")

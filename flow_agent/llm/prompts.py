from typing import Any


def build_messages(
    system_prompt: str,
    user_input: str,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
    ]

    if history:
        messages.extend(history)

    messages.append({"role": "user", "content": user_input})
    return messages

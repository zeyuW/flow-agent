from dataclasses import dataclass


@dataclass(slots=True)
class PromptBudget:
    """Simple prompt budgeting by character length."""

    max_chars: int = 8000
    history_chars: int = 3000
    memory_chars: int = 1500
    tool_trace_chars: int = 1000


class PromptAssembler:
    """Assemble block-based prompt with trim strategy."""

    def __init__(self, budget: PromptBudget) -> None:
        self.budget = budget

    def assemble(
        self,
        *,
        system_block: str,
        persona_block: str,
        history: list[dict[str, str]],
        user_input: str,
        memory_block: str = "",
        retrieval_block: str = "",
        tool_instructions: str = "",
        runtime_block: str = "",
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_block},
            {"role": "system", "content": persona_block},
        ]
        if runtime_block:
            messages.append({"role": "system", "content": self._trim(runtime_block, 800)})
        if tool_instructions:
            messages.append({"role": "system", "content": self._trim(tool_instructions, self.budget.tool_trace_chars)})
        if memory_block:
            messages.append({"role": "system", "content": self._trim(memory_block, self.budget.memory_chars)})
        if retrieval_block:
            messages.append({"role": "system", "content": self._trim(retrieval_block, self.budget.memory_chars)})

        trimmed_history = self._trim_history(history, self.budget.history_chars)
        messages.extend(trimmed_history)
        messages.append({"role": "user", "content": user_input})

        # global hard cap
        total = sum(len(m.get("content", "")) for m in messages)
        if total > self.budget.max_chars:
            overflow = total - self.budget.max_chars
            # Trim history first when overflow happens.
            for idx in range(len(messages) - 2, 1, -1):
                content = messages[idx].get("content", "")
                if overflow <= 0:
                    break
                cut = min(len(content), overflow)
                messages[idx]["content"] = content[cut:]
                overflow -= cut
        return messages

    @staticmethod
    def _trim(text: str, limit: int) -> str:
        return text if len(text) <= limit else text[:limit] + "\n...<trimmed>"

    def _trim_history(self, history: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
        picked: list[dict[str, str]] = []
        used = 0
        for msg in reversed(history):
            content = msg.get("content", "")
            size = len(content)
            if used + size > limit:
                break
            picked.append(msg)
            used += size
        picked.reverse()
        return picked


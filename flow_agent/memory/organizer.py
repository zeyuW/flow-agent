from typing import Protocol

from flow_agent.memory.store import MessageStore

# 记忆整理器接口
class MemoryOrganizer(Protocol):
    def organize(self, session_id: str) -> dict[str, int]:
        ...


# 简单记忆整理器
class SimpleMemoryOrganizer:
    def __init__(
        self,
        store: MessageStore,
        *,
        max_messages: int = 200,
        dedupe: bool = True,
    ) -> None:
        self.store = store
        self.max_messages = max_messages
        self.dedupe = dedupe
    # 整理记忆
    def organize(self, session_id: str) -> dict[str, int]:
        original = self.store.list_messages(session_id)
        cleaned = self._clean(original)
        self.store.replace_messages(session_id, cleaned)
        return {"before": len(original), "after": len(cleaned)}
    # 清理记忆
    def _clean(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        # 1) 过滤空内容
        filtered: list[dict[str, str]] = []
        for msg in messages:
            role = msg.get("role", "").strip()
            content = (msg.get("content") or "").strip()
            if not role or not content:
                continue
            # 2) 去掉高噪声固定话术（最小版，避免污染检索）
            if "无法长期存储个人信息" in content:
                continue
            filtered.append({"role": role, "content": content})

        # 3) 去重（保留第一次出现）
        if self.dedupe:
            seen: set[tuple[str, str]] = set()
            deduped: list[dict[str, str]] = []
            for msg in filtered:
                key = (msg["role"], msg["content"])
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(msg)
            filtered = deduped

        # 4) 裁剪，只保留最新 N 条
        if self.max_messages > 0 and len(filtered) > self.max_messages:
            filtered = filtered[-self.max_messages :]
        return filtered


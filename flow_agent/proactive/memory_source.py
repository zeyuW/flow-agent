from flow_agent.memory.store import MessageStore
from flow_agent.proactive.models import ProactiveCandidate


class MemoryFollowUpSource:
    def __init__(self, store: MessageStore, session_id: str = "default") -> None:
        self.store = store
        self.session_id = session_id

    def fetch_candidates(self) -> list[ProactiveCandidate]:
        history = self.store.list_messages(self.session_id)
        candidates: list[ProactiveCandidate] = []
        # 最小版：扫描最近用户消息，碰到问句则产生跟进候选
        for msg in reversed(history[-10:]):
            if msg.get("role") != "user":
                continue
            content = (msg.get("content") or "").strip()
            if not content:
                continue
            if "?" in content or "？" in content:
                key = f"memory_followup:{content.lower()}"
                candidates.append(
                    ProactiveCandidate(
                        key=key,
                        content=f"[Follow-up] 你之前问过：{content}",
                        source="memory_followup",
                        priority=0.7,
                    )
                )
                break
        return candidates

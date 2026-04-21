from flow_agent.proactive.models import ProactiveCandidate


class CandidateRanker:
    def rank(self, candidates: list[ProactiveCandidate]) -> list[ProactiveCandidate]:
        # 最小版：按 priority 倒序，再按 key 稳定排序
        return sorted(candidates, key=lambda c: (-c.priority, c.key))

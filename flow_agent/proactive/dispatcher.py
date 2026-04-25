from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Callable

from flow_agent.proactive.types import ProactiveCandidate


class ProactiveDispatcher(Protocol):
    def dispatch(self, candidate: ProactiveCandidate) -> None:
        ...


@dataclass(slots=True)
class QQProactiveDispatcher:
    """Dispatch proactive content to a QQ private chat."""

    qq_user_id: int
    send_private_msg: Callable[[int, str], None]

    def dispatch(self, candidate: ProactiveCandidate) -> None:
        self.send_private_msg(self.qq_user_id, candidate.content)

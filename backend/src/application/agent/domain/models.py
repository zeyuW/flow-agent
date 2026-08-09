from dataclasses import dataclass


@dataclass(slots=True)
class AgentResponse:
    content: str

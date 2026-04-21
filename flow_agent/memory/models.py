from dataclasses import dataclass


@dataclass(slots=True)
class RetrievedMemory:
    role: str
    content: str
    score: float


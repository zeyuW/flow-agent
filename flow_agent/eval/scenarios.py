from dataclasses import dataclass
from typing import Callable


@dataclass(slots=True)
class EvalScenario:
    """One executable evaluation scenario."""

    name: str
    run: Callable[[], dict[str, object]]
    tags: tuple[str, ...] = ()


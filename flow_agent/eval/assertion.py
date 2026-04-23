from dataclasses import dataclass


@dataclass(slots=True)
class AssertionResult:
    ok: bool
    diff: dict[str, object]


def compare_loose(
    actual: dict[str, object],
    expected: dict[str, object],
    keys: tuple[str, ...] = ("status", "branch", "tool_trace", "retrieval_trace"),
) -> AssertionResult:
    """Loose comparison on selected keys."""

    diff: dict[str, object] = {}
    for key in keys:
        if key not in expected:
            continue
        if actual.get(key) != expected.get(key):
            diff[key] = {"actual": actual.get(key), "expected": expected.get(key)}
    return AssertionResult(ok=not diff, diff=diff)


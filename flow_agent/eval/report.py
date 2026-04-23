from dataclasses import dataclass


@dataclass(slots=True)
class EvalReport:
    total: int
    passed: int
    failed: int
    details: list[dict[str, object]]


def build_report(results: list[dict[str, object]]) -> EvalReport:
    passed = sum(1 for r in results if bool(r.get("ok")))
    total = len(results)
    return EvalReport(
        total=total,
        passed=passed,
        failed=total - passed,
        details=results,
    )


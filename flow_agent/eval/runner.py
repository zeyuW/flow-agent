from dataclasses import dataclass

from flow_agent.eval.assertion import compare_loose
from flow_agent.eval.baseline import BaselineStore
from flow_agent.eval.report import EvalReport, build_report
from flow_agent.eval.scenarios import EvalScenario


@dataclass(slots=True)
class EvalRunner:
    """Run scenarios and compare with baseline."""

    scenarios: list[EvalScenario]
    baseline_store: BaselineStore

    def run_all(self, *, update_baseline: bool = False) -> EvalReport:
        baseline = self.baseline_store.load()
        results: list[dict[str, object]] = []
        next_baseline: dict[str, object] = dict(baseline)
        for scenario in self.scenarios:
            actual = scenario.run()
            expected = baseline.get(scenario.name)
            if expected is None:
                ok = True
                diff: dict[str, object] = {}
            else:
                assert isinstance(expected, dict)
                assertion = compare_loose(actual=actual, expected=expected)
                ok = assertion.ok
                diff = assertion.diff
            results.append(
                {
                    "scenario": scenario.name,
                    "ok": ok,
                    "diff": diff,
                    "actual": actual,
                }
            )
            if update_baseline or expected is None:
                next_baseline[scenario.name] = actual
        if update_baseline:
            self.baseline_store.save(next_baseline)
        return build_report(results)


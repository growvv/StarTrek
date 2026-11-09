"""Run benchmark cases through an injected case runner."""

from __future__ import annotations

from typing import Callable

from specfcg.benchmark.cases import NLTestCase
from specfcg.models import RunResult


class Runner:
    def __init__(
        self, run_case: Callable[[str], RunResult]
    ) -> None:
        self.run_case = run_case

    def run(self, cases: list[NLTestCase]) -> list[dict]:
        rows: list[dict] = []
        for case in cases:
            result = self.run_case(case.id)
            rows.append(
                {
                    "case_id": case.id,
                    "success": result.success,
                    "goal_success": result.goal_success,
                    "steps": len(result.step_results),
                    "failure_type": result.failure_type,
                }
            )
        return rows

"""User-level pilot runs with per-case reset and latency metrics."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from specfcg.benchmark.cases import NLTestCase


@dataclass
class PilotRow:
    case_id: str
    goal: str
    planned: bool
    path: list[str]
    steps: int
    actions_ok: int
    success: bool
    goal_success: bool
    failure_type: str | None
    error: str
    llm_calls: int
    reset_s: float
    plan_s: float
    execute_s: float


class Pilot:
    def __init__(
        self,
        pipeline: Any,
        reset: Callable[[], None] | None = None,
        app: str = "",
        detail_dir: Path | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.reset = reset
        self.app = app
        self.detail_dir = detail_dir

    def _misses(self) -> int:
        return int(getattr(self.pipeline.llm, "misses", 0))

    def _write_detail(
        self, case_id: str, plan: Any, result: Any
    ) -> None:
        if self.detail_dir is None:
            return
        path = Path(self.detail_dir) / f"{case_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "plan": asdict(plan) if plan is not None else None,
            "result": asdict(result) if result is not None else None,
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def run_case(self, case: NLTestCase) -> PilotRow:
        started = time.perf_counter()
        if self.reset is not None:
            self.reset()
        reset_s = time.perf_counter() - started

        misses_before = self._misses()
        state = self.pipeline.device.dump_ui()

        started = time.perf_counter()
        plan = self.pipeline.plan(case.text, state, self.app)
        plan_s = time.perf_counter() - started

        if plan is None:
            self._write_detail(case.id, None, None)
            return PilotRow(
                case_id=case.id,
                goal=case.text,
                planned=False,
                path=[],
                steps=0,
                actions_ok=0,
                success=False,
                goal_success=False,
                failure_type="goal_failure",
                error="no plan for this case",
                llm_calls=self._misses() - misses_before,
                reset_s=round(reset_s, 3),
                plan_s=round(plan_s, 3),
                execute_s=0.0,
            )

        started = time.perf_counter()
        result = self.pipeline.executor.execute(plan)
        execute_s = time.perf_counter() - started
        self._write_detail(case.id, plan, result)

        actions_ok = sum(
            1
            for step in result.step_results
            if isinstance(step, dict) and step.get("success")
        )
        return PilotRow(
            case_id=case.id,
            goal=case.text,
            planned=True,
            path=list(plan.path),
            steps=len(result.step_results),
            actions_ok=actions_ok,
            success=bool(result.success),
            goal_success=bool(result.goal_success),
            failure_type=result.failure_type,
            error=result.error,
            llm_calls=self._misses() - misses_before,
            reset_s=round(reset_s, 3),
            plan_s=round(plan_s, 3),
            execute_s=round(execute_s, 3),
        )

    def run(self, cases: list[NLTestCase]) -> list[PilotRow]:
        return [self.run_case(case) for case in cases]

    def run_to_jsonl(
        self, cases: list[NLTestCase], path: Path
    ) -> list[PilotRow]:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        rows: list[PilotRow] = []
        with path.open("w", encoding="utf-8") as handle:
            for case in cases:
                row = self.run_case(case)
                rows.append(row)
                handle.write(
                    json.dumps(asdict(row), ensure_ascii=False) + "\n"
                )
                handle.flush()
        return rows

    @staticmethod
    def write_jsonl(rows: list[PilotRow], path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(asdict(row), ensure_ascii=False) for row in rows
        ]
        text = "\n".join(lines)
        if text:
            text += "\n"
        path.write_text(text, encoding="utf-8")

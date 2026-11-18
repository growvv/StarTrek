"""Run benchmark tasks under the 20-step cap and score the final state.

The runner owns everything except the agent: it initialises app state,
enforces the step budget, detects loops, evaluates the oracle, and writes
one latest record per task.  The agent itself is injected, so the same
runner measures our planner/executor, an open-source baseline, or a random
traversal without special cases.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from specfcg.benchmark.failures import classify_failure
from specfcg.benchmark.harness import Ops, collect_final_state, prepare_state
from specfcg.benchmark.oracles import evaluate_oracle
from specfcg.benchmark.store import LatestStore
from specfcg.benchmark.suite import BenchTask

LOOP_REPEATS = 3


@dataclass
class AgentRun:
    steps: list[dict[str, Any]] = field(default_factory=list)
    done: bool = False
    no_plan: bool = False
    error: str = ""
    predicted_path: list[str] = field(default_factory=list)
    predicted_confidence: float = 0.0
    reached_cards: list[str] = field(default_factory=list)
    observed_ui: list[str] = field(default_factory=list)
    # The exact string handed to the agent.  The ablation compares two arms
    # that differ in this string and nothing else, so the string is evidence.
    task_text: str = ""


@dataclass
class TaskOutcome:
    task_id: str
    app: str
    goal: str
    success: bool
    failure_type: str | None
    reason: str
    steps: int
    max_steps: int
    complexity: float
    tags: list[str]
    oracle_evidence: str
    predicted_path: list[str]
    predicted_confidence: float
    reached_cards: list[str]
    actions: list[dict[str, Any]]
    task_text: str = ""
    error: str = ""

    def as_record(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "app": self.app,
            "goal": self.goal,
            "success": self.success,
            "failure_type": self.failure_type,
            "reason": self.reason,
            "steps": self.steps,
            "max_steps": self.max_steps,
            "complexity": self.complexity,
            "tags": self.tags,
            "oracle_evidence": self.oracle_evidence,
            "predicted_path": self.predicted_path,
            "predicted_confidence": self.predicted_confidence,
            "reached_cards": self.reached_cards,
            "actions": self.actions,
            "task_text": self.task_text,
            "error": self.error,
        }


def detect_loop(steps: list[dict[str, Any]]) -> str:
    """Return the repeated action signature, or '' when the run progresses."""
    repeats = 0
    previous = ""
    for step in steps:
        signature = (
            f"{step.get('action')}:{step.get('target')}:{step.get('args')}"
        )
        repeats = repeats + 1 if signature == previous else 1
        previous = signature
        if repeats >= LOOP_REPEATS:
            return signature
    return ""


def _crashed(error: str) -> bool:
    return bool(
        re.search(
            r"FATAL|crash|ANR|has stopped|Process .* died",
            error or "",
            re.IGNORECASE,
        )
    )


class TaskRunner:
    def __init__(
        self,
        ops: Ops,
        *,
        settle_s: float = 0.0,
        out_dir: Path | None = None,
    ) -> None:
        self.ops = ops
        self.settle_s = settle_s
        self.out_dir = Path(out_dir) if out_dir else None

    def run(
        self,
        task: BenchTask,
        agent: Callable[[BenchTask], AgentRun],
    ) -> TaskOutcome:
        init_error = ""
        try:
            prepare_state(self.ops, task)
        except Exception as exc:  # noqa: BLE001
            init_error = repr(exc)

        run = AgentRun()
        if not init_error:
            try:
                run = agent(task)
            except Exception as exc:  # noqa: BLE001
                run = AgentRun(error=f"agent error: {exc!r}")

        steps = list(run.steps)[: task.max_steps]
        looped_signature = detect_loop(steps)
        try:
            state = collect_final_state(self.ops, task.oracle)
            oracle = evaluate_oracle(task.oracle, state)
            oracle_error = ""
        except Exception as exc:  # noqa: BLE001
            from specfcg.benchmark.oracles import OracleResult

            oracle = OracleResult(False, repr(exc), "")
            oracle_error = repr(exc)

        success = bool(oracle.success and not init_error and not run.error)
        timed_out = "timeout" in (run.error or "").lower()
        failure_type = classify_failure(
            success=success,
            timed_out=timed_out,
            crashed=_crashed(run.error),
            init_error=init_error,
            no_plan=run.no_plan,
            steps=len(steps),
            max_steps=task.max_steps,
            looped=bool(looped_signature),
            action_failed=any(not step.get("ok", True) for step in steps),
            oracle_error=oracle_error,
        )
        if failure_type == "loop_detected":
            reason = f"repeated action {looped_signature}"
        elif init_error:
            reason = f"init failed: {init_error}"
        elif run.error:
            reason = run.error
        elif success:
            reason = oracle.reason
        else:
            reason = oracle.reason

        outcome = TaskOutcome(
            task_id=task.id,
            app=task.app,
            goal=task.goal,
            success=success,
            failure_type=failure_type,
            reason=reason,
            steps=len(steps),
            max_steps=task.max_steps,
            complexity=task.complexity,
            tags=list(task.tags),
            oracle_evidence=oracle.evidence,
            predicted_path=list(run.predicted_path),
            predicted_confidence=float(run.predicted_confidence),
            reached_cards=list(run.reached_cards),
            actions=steps,
            task_text=run.task_text,
            error=run.error,
        )
        self._write(outcome)
        return outcome

    def _write(self, outcome: TaskOutcome) -> None:
        if self.out_dir is None:
            return
        tasks_dir = self.out_dir / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)
        path = tasks_dir / f"{outcome.task_id}.json"
        path.write_text(
            json.dumps(
                outcome.as_record(), ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )
        LatestStore(self.out_dir / "latest.json").update(
            outcome.task_id, outcome.as_record()
        )

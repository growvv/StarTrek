"""Execute a TestPlan on a device and validate contracts."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from specfcg.executor.device import Device
from specfcg.executor.summarizer import StateSummarizer
from specfcg.llm.client import LLMClient, LLMParseError
from specfcg.models import (
    Graph,
    PlanStep,
    RunResult,
    Step,
    TestPlan,
    Trace,
    as_bool,
)

logger = logging.getLogger(__name__)

_POST_SCHEMA = '{"satisfied": true, "reason": "why"}'
_GOAL_SCHEMA = '{"achieved": true, "reason": "why"}'


class Executor:
    def __init__(
        self,
        device: Device,
        llm: LLMClient,
        summarizer: StateSummarizer,
        graph: Graph,
    ) -> None:
        self.device = device
        self.llm = llm
        self.summarizer = summarizer
        self.graph = graph

    @staticmethod
    def _groups(steps: list[PlanStep]) -> list[tuple[str, list[PlanStep]]]:
        groups: list[tuple[str, list[PlanStep]]] = []
        for step in steps:
            if not groups or groups[-1][0] != step.card:
                groups.append((step.card, [step]))
            else:
                groups[-1][1].append(step)
        return groups

    def _result(
        self,
        plan: TestPlan,
        trace: Trace,
        step_results: list[dict[str, Any]],
        *,
        success: bool,
        goal_success: bool = False,
        failure_type: str | None = None,
        error: str = "",
    ) -> RunResult:
        return RunResult(
            plan=plan,
            success=success,
            goal_success=goal_success,
            failure_type=failure_type,  # type: ignore[arg-type]
            new_trace=trace,
            step_results=step_results,
            error=error,
        )

    def execute(self, plan: TestPlan) -> RunResult:
        app = plan.app or plan.goal.app
        self.device.start_app(app)
        initial_ui = self.device.dump_ui()
        initial_summary = self.summarizer.summarize(initial_ui)

        trace = Trace(
            trace_id=f"run-{uuid.uuid4().hex}",
            app=app,
            start_state=initial_summary,
            goal=plan.goal.description,
        )
        step_results: list[dict[str, Any]] = []
        state = initial_ui

        for card_name, steps in self._groups(plan.steps):
            for step in steps:
                before = self.device.dump_ui()
                ok = self.device.execute(step.action, step.target, step.args)
                after = self.device.dump_ui()
                state = after
                trace.steps.append(
                    Step(
                        action=step.action,
                        target=step.target,
                        args=step.args,
                        before_state=before,
                        after_state=after,
                        success=ok,
                    )
                )
                step_results.append(
                    {
                        "card": card_name,
                        "action": step.action,
                        "target": step.target,
                        "args": step.args,
                        "success": ok,
                        "before": before,
                        "after": after,
                    }
                )
                if not ok:
                    return self._result(
                        plan,
                        trace,
                        step_results,
                        success=False,
                        failure_type="widget_failure",
                        error=f"action failed: {step.action} {step.target}",
                    )

            card = self.graph.cards.get(card_name)
            if card is None:
                continue
            prompt = (
                f"Card: {card.name}\nIntent: {card.intent}\n"
                f"Postconditions: {card.postconditions}\n"
                f"Observed UI after the last step:\n{state[:4000]}\n\n"
                "Are the postconditions satisfied?"
            )
            try:
                check = self.llm.complete_json(prompt, _POST_SCHEMA)
            except LLMParseError as exc:
                return self._result(
                    plan,
                    trace,
                    step_results,
                    success=False,
                    failure_type="check_error",
                    error=f"postcondition check failed: {exc}",
                )
            if not as_bool(check.get("satisfied", False)):
                return self._result(
                    plan,
                    trace,
                    step_results,
                    success=False,
                    failure_type="postcondition_failure",
                    error=str(check.get("reason", "")),
                )

        goal_prompt = (
            f"Goal: {plan.goal.description}\n"
            f"Assertions: {plan.assertions}\n"
            f"Final UI state:\n{state[:4000]}\n\n"
            "Is the goal achieved?"
        )
        try:
            goal_check = self.llm.complete_json(goal_prompt, _GOAL_SCHEMA)
        except LLMParseError as exc:
            return self._result(
                plan,
                trace,
                step_results,
                success=False,
                failure_type="check_error",
                error=f"goal check failed: {exc}",
            )
        achieved = as_bool(goal_check.get("achieved", False))
        if not achieved:
            return self._result(
                plan,
                trace,
                step_results,
                success=False,
                failure_type="goal_failure",
                error=str(goal_check.get("reason", "")),
            )
        return self._result(
            plan,
            trace,
            step_results,
            success=True,
            goal_success=True,
        )

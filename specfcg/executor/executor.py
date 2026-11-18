"""Execute a TestPlan by handing its description to a GUI agent."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from specfcg.executor.agent import AgentTrace, GuiAgent
from specfcg.executor.summarizer import StateSummarizer
from specfcg.llm.client import LLMClient, LLMParseError
from specfcg.models import Graph, RunResult, Step, TestPlan, Trace, as_bool

logger = logging.getLogger(__name__)

_GOAL_SCHEMA = '{"achieved": true, "reason": "why"}'


class Executor:
    """Hand a plan's description to the agent, then judge the outcome.

    The executor owns no device and sends no action.  The plan is a
    description; the agent reads it and decides what to do; the executor
    records what happened and asks whether the goal was reached.  That split
    is the point of the round: a plan that could be replayed would measure
    the recorder, not the map.
    """

    def __init__(
        self,
        agent: GuiAgent,
        llm: LLMClient,
        graph: Graph,
        summarizer: StateSummarizer | None = None,
        max_steps: int = 20,
    ) -> None:
        self.agent = agent
        self.llm = llm
        self.graph = graph
        self.summarizer = summarizer
        self.max_steps = max_steps

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

    def _start_state(self, initial_ui: str) -> str:
        if self.summarizer is not None:
            return self.summarizer.summarize(initial_ui)
        return initial_ui[:2000]

    @staticmethod
    def _step_results(agent_trace: AgentTrace) -> list[dict[str, Any]]:
        return [
            {
                "action": step.action,
                "target": step.target,
                "args": step.args,
                "success": step.success,
                "before": step.before_state,
                "after": step.after_state,
            }
            for step in agent_trace.steps
        ]

    @staticmethod
    def _action_log(agent_trace: AgentTrace) -> str:
        return "\n".join(
            f"- {step.action} {step.target}".rstrip()
            + (f" args={step.args}" if step.args else "")
            for step in agent_trace.steps
        )

    def execute(
        self, plan: TestPlan, max_steps: int | None = None
    ) -> RunResult:
        app = plan.app or plan.goal.app
        budget = self.max_steps if max_steps is None else max_steps
        agent_trace = self.agent.run(
            plan.description, budget, app=app
        )

        trace = Trace(
            trace_id=f"run-{uuid.uuid4().hex}",
            app=app,
            start_state=self._start_state(agent_trace.initial_ui),
            goal=plan.goal.description,
            steps=list(agent_trace.steps),
            metadata={
                "task_description": plan.description,
                "agent_done": agent_trace.done,
            },
        )
        step_results = self._step_results(agent_trace)

        if agent_trace.error:
            return self._result(
                plan,
                trace,
                step_results,
                success=False,
                failure_type="environment_failure",
                error=agent_trace.error,
            )

        goal_prompt = (
            f"Goal: {plan.goal.description}\n"
            f"Assertions: {plan.assertions}\n"
            f"Actions taken:\n{self._action_log(agent_trace)}\n\n"
            f"Final UI state:\n{agent_trace.final_ui[:4000]}\n\n"
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

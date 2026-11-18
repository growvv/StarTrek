"""Agent adapters: graph-planned execution, and a random-traversal baseline.

Both produce the same ``AgentRun`` shape, so the task runner stays agnostic.
No agent policy is reimplemented here: ``GraphAgent`` plans with the graph and
hands the description to the pipeline's agent; the random adapter is the
standard "tap something unexplored" baseline used to judge whether a graph
reaches an app's functions at all.
"""

from __future__ import annotations

import random
import re
from typing import Any, Callable

from specfcg.benchmark.suite import BenchTask
from specfcg.benchmark.suite_runner import AgentRun
from specfcg.executor.device import Device


class RawGoalAgent:
    """The control arm: the same agent, given the raw goal.

    Nothing here plans.  The agent is handed the user's own words and has to
    work out what to do, which is exactly what a user does.  Its success is
    the agent's competence; only the paired difference against the graph arm
    is the graph's contribution.
    """

    def __init__(self, agent: Any) -> None:
        self.agent = agent

    def __call__(self, task: BenchTask) -> AgentRun:
        trace = self.agent.run(task.goal, task.max_steps, app=task.package)
        return AgentRun(
            steps=[
                {
                    "action": step.action,
                    "target": step.target,
                    "args": step.args,
                    "ok": bool(step.success),
                }
                for step in trace.steps
            ],
            done=trace.done,
            observed_ui=[
                step.before_state for step in trace.steps
            ] + ([trace.final_ui] if trace.final_ui else []),
            task_text=task.goal,
            error=trace.error,
        )


class GraphAgent:
    """Plan with the Function Contract Graph, then let the agent execute.

    Observation and action go through the same client, so the state the plan
    is made from is the state the agent acts on.  The agent callable takes the
    task rather than ``(goal, max_steps)`` because the app is part of what the
    agent needs and the runner already has it.
    """

    def __init__(
        self,
        pipeline: Any,
        confidence: Callable[[list[str]], float] | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.confidence = confidence

    def __call__(self, task: BenchTask) -> AgentRun:
        agent = self.pipeline.executor.agent
        state = agent.observe(task.package)
        plan = self.pipeline.plan(task.goal, state, app=task.package)
        if plan is None or not plan.path:
            return AgentRun(steps=[], no_plan=True)
        result = self.pipeline.executor.execute(
            plan, max_steps=task.max_steps
        )
        steps = [
            {
                "action": item.get("action", ""),
                "target": item.get("target", ""),
                "args": item.get("args", ""),
                "ok": bool(item.get("success")),
            }
            for item in result.step_results
        ]
        observed = [
            item.get("before", "") for item in result.step_results
        ]
        if result.new_trace is not None and result.new_trace.steps:
            observed.append(result.new_trace.steps[-1].after_state)
        run = AgentRun(
            steps=steps,
            done=bool(result.success),
            predicted_path=list(plan.path),
            reached_cards=list(plan.path) if result.success else [],
            observed_ui=observed,
            task_text=plan.description,
            error=result.error,
        )
        if self.confidence is not None:
            run.predicted_confidence = self.confidence(list(plan.path))
        return run


_CLICKABLE_RE = re.compile(
    r'(?:text|content-desc)="([^"]+)"', re.IGNORECASE
)


def _visible_targets(ui: str) -> list[str]:
    """Clickable labels in the compact UI dump, most specific first."""
    targets: list[str] = []
    seen: set[str] = set()
    for match in _CLICKABLE_RE.finditer(ui or ""):
        label = match.group(1).strip()
        if not label or label in seen:
            continue
        seen.add(label)
        targets.append(label)
    for match in re.finditer(r'resource-id="([^"]+)"', ui or ""):
        rid = match.group(1).strip()
        if rid and rid not in seen:
            seen.add(rid)
            targets.append(rid)
    return targets


class RandomTraversalAgent:
    """The control condition: explore with no graph, no goal understanding."""

    def __init__(
        self,
        device: Device,
        rng: random.Random | None = None,
        actions: tuple[str, ...] = ("click", "back", "swipe"),
    ) -> None:
        self.device = device
        self.rng = rng or random.Random(0)
        self.actions = actions
        self.seen_targets: set[str] = set()

    def __call__(self, task: BenchTask) -> AgentRun:
        steps: list[dict[str, Any]] = []
        observed: list[str] = []
        for _ in range(task.max_steps):
            ui = self.device.dump_ui()
            observed.append(ui)
            targets = [
                target
                for target in _visible_targets(ui)
                if target not in self.seen_targets
            ]
            action = self.rng.choice(self.actions)
            if action == "click" and targets:
                target = self.rng.choice(targets)
                self.seen_targets.add(target)
                args = ""
            elif action == "swipe":
                target = ""
                args = "500,1600,500,900"
            else:
                action = "back"
                target = ""
                args = ""
            ok = self.device.execute(action, target, args)
            steps.append(
                {
                    "action": action,
                    "target": target,
                    "args": args,
                    "ok": bool(ok),
                }
            )
            if not ok:
                break
        return AgentRun(steps=steps, done=False, observed_ui=observed)

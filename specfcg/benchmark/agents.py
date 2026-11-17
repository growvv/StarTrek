"""Agent adapters: SpecFCG planner+executor, and a random-traversal baseline.

Both produce the same ``AgentRun`` shape, so the task runner stays agnostic.
No agent policy is reimplemented here: the SpecFCG adapter calls the existing
``Pipeline``/``Executor``; the random adapter is the standard "tap something
unexplored" baseline used to judge whether a graph reaches an app's
functions at all.
"""

from __future__ import annotations

import random
import re
from typing import Any, Callable

from specfcg.benchmark.suite_runner import AgentRun
from specfcg.executor.device import Device
from specfcg.models import PlanStep, TestPlan


def execute_plan(
    device: Device,
    plan: TestPlan,
    *,
    max_steps: int,
    reached_cards: set[str],
) -> AgentRun:
    """Run a compiled plan on the device under the benchmark step budget."""
    steps: list[dict[str, Any]] = []
    reached: list[str] = []
    observed: list[str] = []
    previous_card = ""
    for step in plan.steps:
        if len(steps) >= max_steps:
            break
        # Record the screen the step acts on: a plan run is evidence about
        # what the app showed along the way, not only where it ended.
        observed.append(device.dump_ui())
        ok = device.execute(step.action, step.target, step.args)
        steps.append(
            {
                "action": step.action,
                "target": step.target,
                "args": step.args,
                "ok": bool(ok),
                "card": step.card,
            }
        )
        if ok and step.card and step.card != previous_card:
            if step.card not in reached_cards:
                reached_cards.add(step.card)
            if step.card not in reached:
                reached.append(step.card)
        previous_card = step.card
    # A failed action is recorded and the run continues: the plan is a
    # hypothesis, a later step may still reach the goal, and the benchmark's
    # oracle -- not an intermediate miss -- decides success.
    done = len(steps) == len(plan.steps) and all(
        step["ok"] for step in steps
    )
    return AgentRun(
        steps=steps,
        done=done,
        predicted_path=list(plan.path),
        reached_cards=reached,
        observed_ui=observed,
    )


class SpecFCGAgent:
    """Plan with the Function Contract Graph, then execute the plan."""

    def __init__(
        self,
        pipeline: Any,
        device: Device,
        reached_cards: set[str],
        confidence: Callable[[list[str]], float] | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.device = device
        self.reached_cards = reached_cards
        self.confidence = confidence

    def __call__(self, goal: str, max_steps: int) -> AgentRun:
        state = self.device.dump_ui()
        plan = self.pipeline.plan(goal, state, app="")
        if plan is None or not plan.steps:
            return AgentRun(steps=[], no_plan=True)
        run = execute_plan(
            self.device,
            plan,
            max_steps=max_steps,
            reached_cards=self.reached_cards,
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

    def __call__(self, goal: str, max_steps: int) -> AgentRun:
        steps: list[dict[str, Any]] = []
        observed: list[str] = []
        for _ in range(max_steps):
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

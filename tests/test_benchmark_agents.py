from __future__ import annotations

from specfcg.benchmark.agents import execute_plan
from specfcg.models import Goal, PlanStep, TestPlan as CompiledPlan


class FakeDevice:
    def __init__(self, results=None) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.results = list(results or [])
        self._i = 0

    def start_app(self, app: str) -> None:
        pass

    def dump_ui(self) -> str:
        return f"state-{len(self.calls)}"

    def execute(self, action: str, target: str, args: str = "") -> bool:
        self.calls.append((action, target, args))
        if self._i < len(self.results):
            ok = self.results[self._i]
            self._i += 1
            return ok
        return True

    def screenshot(self, path) -> None:
        pass


def _plan(steps: list[PlanStep], path: list[str]) -> CompiledPlan:
    return CompiledPlan(
        goal=Goal(description="do it"),
        path=path,
        steps=steps,
        app="it.feio.android.omninotes.foss",
    )


def test_execute_plan_stops_at_the_step_cap():
    device = FakeDevice()
    steps = [
        PlanStep(card="create_note", action="click", target=f"t{i}")
        for i in range(6)
    ]

    run = execute_plan(
        device,
        _plan(steps, ["create_note"]),
        max_steps=3,
        reached_cards=set(),
    )

    assert len(run.steps) == 3
    assert len(device.calls) == 3


def test_execute_plan_keeps_going_after_an_action_failure():
    """A failed step is evidence, not a verdict.

    The benchmark judges the final state, and a plan is a hypothesis: a tap
    that misses (an optional toolbar button, a control that moved) does not
    mean the rest of the route cannot still reach the goal.  The runner
    records the failed action and the oracle decides.
    """
    device = FakeDevice(results=[True, False, True])
    steps = [
        PlanStep(card="create_note", action="click", target="a"),
        PlanStep(card="create_note", action="click", target="b"),
        PlanStep(card="create_note", action="click", target="c"),
    ]

    run = execute_plan(
        device,
        _plan(steps, ["create_note"]),
        max_steps=20,
        reached_cards=set(),
    )

    assert len(run.steps) == 3
    assert [step["ok"] for step in run.steps] == [True, False, True]
    assert run.done is False


def test_execute_plan_records_reached_cards_per_card():
    device = FakeDevice()
    steps = [
        PlanStep(card="create_note", action="click", target="a"),
        PlanStep(card="create_note", action="click", target="b"),
        PlanStep(card="open_note", action="click", target="c"),
    ]
    reached: set[str] = set()

    run = execute_plan(
        device,
        _plan(steps, ["create_note", "open_note"]),
        max_steps=20,
        reached_cards=reached,
    )

    assert reached == {"create_note", "open_note"}
    assert run.reached_cards == ["create_note", "open_note"]
    assert run.done is True


def test_random_traversal_records_every_observed_screen():
    from specfcg.benchmark.agents import RandomTraversalAgent

    device = FakeDevice()
    agent = RandomTraversalAgent(device, actions=("back",))
    run = agent("anything", max_steps=3)

    assert len(run.observed_ui) == 3
    assert run.observed_ui[0] == "state-0"


def test_execute_plan_records_every_screen_it_acted_on():
    """A plan run is evidence too.

    A probe tests its predicted path by asking whether the function's UI
    appeared along the way.  The random baseline records the screens it
    saw; a plan run must record them the same way, or the probe can only
    look at the final screen and misses a function whose control appeared
    mid-plan.
    """
    device = FakeDevice()
    plan = _plan(
        [
            PlanStep(card="create_note", action="click", target="text=New"),
            PlanStep(card="share_note", action="click", target="text=Share"),
        ],
        ["create_note", "share_note"],
    )

    run = execute_plan(device, plan, max_steps=10, reached_cards=set())

    assert len(run.observed_ui) == 2
    assert run.observed_ui[0] == "state-0"
    assert run.observed_ui[1] == "state-1"

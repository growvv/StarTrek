from __future__ import annotations

from specfcg.benchmark.agents import GraphAgent, RandomTraversalAgent
from specfcg.benchmark.suite import BenchTask
from specfcg.models import Goal, RunResult, Step, TestPlan
from specfcg.executor.agent import ScriptedAgent
from specfcg.executor.executor import Executor
from tests.fakes import FakeLLMClient


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


class _Planner:
    """Stands in for the pipeline's planner: records the state it was given."""

    def __init__(self, path: list[str]) -> None:
        self.path = path
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, goal: str, state: str = "", app: str = ""):
        self.calls.append((goal, state, app))
        return TestPlan(
            goal=Goal(goal, app=app),
            path=list(self.path),
            description=f"Overall goal: {goal}",
            app=app,
        )


class _Pipeline:
    def __init__(self, agent, planner, llm):
        self.executor = Executor(agent, llm, None)
        self._planner = planner

    def plan(self, goal: str, state: str = "", app: str = ""):
        return self._planner(goal, state, app)


def _task(max_steps: int = 20) -> BenchTask:
    return BenchTask(
        id="t1",
        app="omninotes",
        package="it.feio.android.omninotes.foss",
        template="create a note",
        max_steps=max_steps,
    )


def _llm(achieved: bool = True) -> FakeLLMClient:
    llm = FakeLLMClient()
    llm.responses = [{"achieved": achieved, "reason": "checked"}]
    return llm


def test_graph_agent_plans_from_the_state_the_agent_observes():
    """Observation and action go through the same client.

    The state the plan is made from must be the state the agent acts on;
    reading it through a separate device is how the two drift apart.
    """
    agent = ScriptedAgent(initial_ui="notes list", final_ui="notes list")
    planner = _Planner(["create_note"])
    pipeline = _Pipeline(agent, planner, _llm())

    GraphAgent(pipeline)(_task())

    assert planner.calls[0][1] == "notes list"
    assert planner.calls[0][2] == "it.feio.android.omninotes.foss"


def test_graph_agent_passes_the_tasks_step_budget_to_the_executor():
    agent = ScriptedAgent()
    pipeline = _Pipeline(agent, _Planner(["create_note"]), _llm())

    GraphAgent(pipeline)(_task(max_steps=7))

    assert agent.max_steps == [7]


def test_graph_agent_marks_the_path_reached_only_when_the_run_succeeded():
    agent = ScriptedAgent()
    pipeline = _Pipeline(agent, _Planner(["create_note"]), _llm(False))

    run = GraphAgent(pipeline)(_task())

    assert run.predicted_path == ["create_note"]
    assert run.reached_cards == []
    assert run.done is False


def test_graph_agent_reports_the_path_when_the_run_succeeded():
    agent = ScriptedAgent()
    pipeline = _Pipeline(agent, _Planner(["create_note", "share_note"]), _llm(True))

    run = GraphAgent(pipeline)(_task())

    assert run.reached_cards == ["create_note", "share_note"]
    assert run.done is True


def test_graph_agent_reports_no_plan_when_the_planner_finds_nothing():
    agent = ScriptedAgent()
    pipeline = _Pipeline(agent, _Planner([]), _llm())

    run = GraphAgent(pipeline)(_task())

    assert run.no_plan is True
    assert run.steps == []


def test_graph_agent_records_the_screens_the_agent_acted_on():
    agent = ScriptedAgent(
        steps=[
            Step(action="click", target="text=New", before_state="s0", after_state="s1"),
            Step(action="click", target="text=Save", before_state="s1", after_state="s2"),
        ]
    )
    pipeline = _Pipeline(agent, _Planner(["create_note"]), _llm(True))

    run = GraphAgent(pipeline)(_task())

    assert run.observed_ui[:2] == ["s0", "s1"]
    assert run.observed_ui[-1] == "s2"


def test_random_traversal_records_every_observed_screen():
    device = FakeDevice()
    agent = RandomTraversalAgent(device, actions=("back",))
    run = agent(_task(max_steps=3))

    assert len(run.observed_ui) == 3
    assert run.observed_ui[0] == "state-0"

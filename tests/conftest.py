from __future__ import annotations

from dataclasses import replace

import pytest

from specfcg.cards.store import CardStore
from specfcg.executor.device import FakeDevice
from specfcg.graph.store import GraphStore
from specfcg.maintainer.builder import EdgeBuilder
from specfcg.maintainer.miner import CardMiner
from specfcg.models import (
    Edge,
    FunctionCard,
    Goal,
    Graph,
    PlanStep,
    RunResult,
    Step,
    TestPlan,
    Trace,
)
from tests.fakes import FakeLLMClient


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient()


@pytest.fixture
def sample_card() -> FunctionCard:
    return FunctionCard(
        name="create_note",
        intent="Create a new note with a title and optional content.",
        inputs=["title", "content (optional)"],
        preconditions="Logged in; on the notes list screen.",
        postconditions="A note with the given title appears in the notes list.",
        effects_outputs="Adds a note to the list; the new note is identified by its title.",
        steps=['Tap "+".', "Enter the title.", "Enter the content.", 'Tap "Save".'],
        evidence=["t1", "t2"],
        success_count=2,
        attempt_count=3,
    )


@pytest.fixture
def another_card() -> FunctionCard:
    return FunctionCard(
        name="share_note",
        intent="Share an existing note through another app.",
        inputs=["note", "channel"],
        preconditions="A note exists and is open.",
        postconditions="The note is shared through the chosen channel.",
        effects_outputs="Sends the note; returns to the note screen.",
        steps=['Tap "Share".', "Choose a channel."],
        evidence=["t1"],
        success_count=1,
        attempt_count=1,
    )


@pytest.fixture
def two_cards(sample_card, another_card) -> dict[str, FunctionCard]:
    return {sample_card.name: sample_card, another_card.name: another_card}


def _card(name: str) -> FunctionCard:
    return FunctionCard(
        name=name,
        intent=f"do {name}",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[],
    )


@pytest.fixture
def sample_trace() -> Trace:
    return Trace(
        trace_id="t1",
        app="omninotes",
        start_state="Notes list",
        goal="create and share a note",
        steps=[
            Step(
                action="click",
                target="text=+",
                before_state="Notes list",
                after_state="Editor",
            ),
            Step(
                action="input",
                target="text=Title",
                args="Trip",
                before_state="Editor",
                after_state="Editor",
            ),
            Step(
                action="click",
                target="text=Share",
                before_state="Editor",
                after_state="Share sheet",
            ),
            Step(
                action="click",
                target="text=Email",
                before_state="Share sheet",
                after_state="Email",
            ),
        ],
        metadata={"source": "fixture"},
    )


@pytest.fixture
def empty_trace() -> Trace:
    return Trace(trace_id="t0", app="omninotes", steps=[])


@pytest.fixture
def single_step_trace() -> Trace:
    return Trace(
        trace_id="t1",
        app="omninotes",
        goal="open the app",
        steps=[
            Step(
                action="click",
                target="text=OmniNotes",
                before_state="Launcher",
                after_state="Notes list",
            )
        ],
    )


@pytest.fixture
def fake_device() -> FakeDevice:
    return FakeDevice(["start"], [True])


@pytest.fixture
def sample_graph(sample_card, another_card) -> Graph:
    planner_share = replace(
        another_card,
        inputs=["note (optional)", "channel (optional)"],
    )
    return Graph(
        cards={
            sample_card.name: sample_card,
            planner_share.name: planner_share,
        },
        edges=[
            Edge(
                from_card=sample_card.name,
                to_card=planner_share.name,
                type="enables",
                description="a created note can be shared",
            )
        ],
    )


@pytest.fixture
def sample_plan(sample_card) -> TestPlan:
    return TestPlan(
        goal=Goal("create a note", app="omninotes"),
        path=[sample_card.name],
        steps=[
            PlanStep(
                card=sample_card.name, action="click", target="text=+"
            ),
            PlanStep(
                card=sample_card.name,
                action="input",
                target="text=Title",
                args="Trip",
            ),
        ],
        assertions=[
            "create a note",
            sample_card.postconditions,
        ],
        app="omninotes",
    )


@pytest.fixture
def graph_store(tmp_path, sample_card, another_card) -> GraphStore:
    cards = CardStore(tmp_path)
    cards.save(sample_card)
    cards.save(another_card)
    return GraphStore(tmp_path, cards)


@pytest.fixture
def edge_builder(fake_llm) -> EdgeBuilder:
    return EdgeBuilder(fake_llm)


@pytest.fixture
def card_miner(fake_llm, tmp_path) -> CardMiner:
    return CardMiner(fake_llm, CardStore(tmp_path))


@pytest.fixture
def successful_result(sample_plan) -> RunResult:
    trace = Trace(
        trace_id="t1",
        app="omninotes",
        steps=[
            Step(action="click", target="text=+"),
            Step(action="input", target="text=Title", args="Trip"),
        ],
    )
    return RunResult(
        plan=sample_plan,
        success=True,
        goal_success=True,
        new_trace=trace,
        step_results=[
            {"card": "create_note", "success": True},
            {"card": "create_note", "success": True},
        ],
    )


@pytest.fixture
def failed_result(sample_plan) -> RunResult:
    trace = Trace(
        trace_id="t1",
        app="omninotes",
        steps=[Step(action="click", target="text=+", success=False)],
    )
    return RunResult(
        plan=sample_plan,
        success=False,
        goal_success=False,
        failure_type="widget_failure",
        new_trace=trace,
        step_results=[{"card": "create_note", "success": False}],
    )


@pytest.fixture
def simple_graph() -> Graph:
    cards = {name: _card(name) for name in ("A", "B", "C")}
    edges = [
        Edge(from_card="A", to_card="C", type="enables"),
        Edge(from_card="C", to_card="B", type="sequence"),
        Edge(from_card="B", to_card="C", type="sequence"),
    ]
    return Graph(cards=cards, edges=edges)


@pytest.fixture
def long_chain() -> Graph:
    names = [f"N{index}" for index in range(9)] + ["Z"]
    cards = {name: _card(name) for name in names}
    edges = [
        Edge(from_card=left, to_card=right, type="sequence")
        for left, right in zip(names, names[1:])
    ]
    return Graph(cards=cards, edges=edges)


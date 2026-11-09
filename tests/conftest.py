from __future__ import annotations

import pytest

from specfcg.models import Edge, FunctionCard, Graph, Step, Trace
from tests.fakes import FakeLLMClient


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient()


@pytest.fixture
def sample_card() -> FunctionCard:
    return FunctionCard(
        name="create_note",
        intent="Create a new note with a title and optional content.",
        inputs=["title", "content"],
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


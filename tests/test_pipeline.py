from __future__ import annotations

from specfcg.cards.store import CardStore
from specfcg.completion.completer import CapabilityCompleter
from specfcg.completion.probe import DeviceProbe
from specfcg.config import AppConfig
from specfcg.executor.device import FakeDevice
from specfcg.executor.executor import Executor
from specfcg.executor.summarizer import StateSummarizer
from specfcg.graph.store import GraphStore
from specfcg.maintainer.builder import EdgeBuilder
from specfcg.maintainer.miner import CardMiner
from specfcg.maintainer.updater import GraphUpdater
from specfcg.models import (
    Edge,
    FunctionCard,
    GraphPatch,
    MissingCapability,
)
from specfcg.pipeline import Pipeline
from specfcg.planner.binding import ParamBinder
from specfcg.planner.compiler import StepCompiler
from specfcg.planner.planner import Planner
from specfcg.planner.retrieval import CardRetriever
from tests.fakes import FakeProbe

CARD_MARKDOWN = """# create_note

**Intent**: Create a new note.
**Inputs**: none
**Preconditions**: On the notes list.
**Postconditions**: A note exists.
**Effects/Outputs**: A new note in the list.
**Steps**:
1. Tap Next
**Evidence**: traces t1; 1/1 successes
"""

SHARE_MARKDOWN = """# share_note

**Intent**: Share an existing note.
**Inputs**: none
**Preconditions**: A note exists.
**Postconditions**: The note is shared.
**Effects/Outputs**: The note leaves the app.
**Steps**:
1. Tap Share
**Evidence**: traces t1; 1/1 successes
"""


def _batch(
    can_execute: bool, is_goal: bool, name: str = "create_note"
) -> dict:
    return {
        "cards": [
            {
                "name": name,
                "can_execute": can_execute,
                "is_goal": is_goal,
            }
        ]
    }


def _card(name: str) -> FunctionCard:
    return FunctionCard(
        name=name,
        intent=f"do {name}",
        inputs=[],
        preconditions="",
        postconditions=f"{name} done",
        effects_outputs="",
        steps=['Tap "Next"'],
    )


def _pipeline(
    tmp_path,
    llm,
    device,
    *,
    cards=(),
    edges=(),
    probe=None,
) -> Pipeline:
    card_store = CardStore(tmp_path)
    for card in cards:
        card_store.save(card)
    store = GraphStore(tmp_path, card_store)
    if edges:
        store.apply_patch(
            GraphPatch(
                edge_updates=[
                    {
                        "from": edge.from_card,
                        "to": edge.to_card,
                        "type": edge.type,
                        "action": "add",
                        "description": edge.description,
                        "evidence": list(edge.evidence),
                    }
                    for edge in edges
                ]
            )
        )

    builder = EdgeBuilder(llm)
    miner = CardMiner(llm, card_store)
    graph = store.load()
    planner = Planner(
        graph,
        llm,
        CardRetriever(llm),
        ParamBinder(llm),
        StepCompiler(llm),
    )
    executor = Executor(device, llm, StateSummarizer(llm), graph)
    updater = GraphUpdater(llm, store, builder)
    completer = CapabilityCompleter(
        llm,
        store,
        miner,
        builder,
        probe if probe is not None else FakeProbe(),
    )
    return Pipeline(
        AppConfig(),
        llm,
        device,
        store,
        card_store,
        miner,
        builder,
        planner,
        executor,
        updater,
        completer,
    )


def test_mine_trace_saves_cards_and_sequence_edges(
    tmp_path, fake_llm, fake_device, sample_trace
):
    fake_llm.responses = [
        {
            "episodes": [
                {"start": 0, "end": 1, "name": "create_note"},
                {"start": 2, "end": 3, "name": "share_note"},
            ]
        },
        CARD_MARKDOWN,
        SHARE_MARKDOWN,
    ]
    pipeline = _pipeline(tmp_path, fake_llm, fake_device)

    patch = pipeline.mine_trace(sample_trace)

    assert {card.name for card in patch.new_cards} == {
        "create_note",
        "share_note",
    }
    assert set(pipeline.card_store.all()) == {"create_note", "share_note"}
    edges = {
        (edge.from_card, edge.to_card, edge.type)
        for edge in pipeline.store.edges()
    }
    assert ("create_note", "share_note", "sequence") in edges


def test_mine_trace_updates_existing_card(
    tmp_path, fake_llm, fake_device, sample_trace, sample_card
):
    fake_llm.responses = [
        {
            "episodes": [
                {"start": 0, "end": 3, "name": "create_note"},
            ]
        },
        CARD_MARKDOWN,
    ]
    pipeline = _pipeline(
        tmp_path, fake_llm, fake_device, cards=[sample_card]
    )

    patch = pipeline.mine_trace(sample_trace)

    assert patch.new_cards == []
    stored = pipeline.card_store.load("create_note")
    assert stored.success_count == 3
    assert stored.attempt_count == 4


def test_build_graph_persists_sequence_and_semantic_edges(
    tmp_path, fake_llm, fake_device
):
    fake_llm.responses = [
        {
            "edges": [
                {
                    "from": "create_note",
                    "to": "share_note",
                    "type": "enables",
                    "description": "a note can be shared",
                }
            ]
        }
    ]
    pipeline = _pipeline(
        tmp_path,
        fake_llm,
        fake_device,
        cards=[_card("create_note"), _card("share_note")],
    )
    segments = [
        {
            "trace_id": "t1",
            "start": 0,
            "end": 0,
            "card": "create_note",
        },
        {
            "trace_id": "t1",
            "start": 1,
            "end": 1,
            "card": "share_note",
        },
    ]

    edges = pipeline.build_graph(segments)

    assert {
        (edge.from_card, edge.to_card, edge.type) for edge in edges
    } == {
        ("create_note", "share_note", "sequence"),
        ("create_note", "share_note", "enables"),
    }
    assert len(pipeline.store.edges()) == 2


def test_plan_wraps_goal_text(tmp_path, fake_llm, fake_device):
    fake_llm.responses = [
        _batch(True, True),
        {"steps": [{"action": "click", "target": "text=Next"}]},
    ]
    pipeline = _pipeline(
        tmp_path, fake_llm, fake_device, cards=[_card("create_note")]
    )

    plan = pipeline.plan("create a note", "Notes list")

    assert plan is not None
    assert plan.goal.description == "create a note"
    assert plan.path == ["create_note"]
    assert plan.steps[0].action == "click"


def test_plan_uses_app_package(tmp_path, fake_llm, fake_device):
    fake_llm.responses = [
        _batch(True, True),
        {"steps": [{"action": "click", "target": "text=Next"}]},
    ]
    pipeline = _pipeline(
        tmp_path, fake_llm, fake_device, cards=[_card("create_note")]
    )

    plan = pipeline.plan(
        "create a note",
        "Notes list",
        app="com.example.omninotes",
    )

    assert plan is not None
    assert plan.goal.app == "com.example.omninotes"
    assert plan.app == "com.example.omninotes"


def test_execute_goal_starts_target_package(
    tmp_path, fake_llm, fake_device
):
    fake_llm.responses = [
        _batch(True, True),
        {"steps": [{"action": "click", "target": "text=Next"}]},
        "Notes list with a plus button",
        {"satisfied": True},
        {"achieved": True},
    ]
    pipeline = _pipeline(
        tmp_path, fake_llm, fake_device, cards=[_card("create_note")]
    )

    result = pipeline.execute_goal(
        "create a note",
        "Notes list",
        app="com.example.omninotes",
    )

    assert result is not None
    assert result.plan is not None
    assert result.plan.app == "com.example.omninotes"
    assert fake_device.app == "com.example.omninotes"


def test_run_goal_executes_and_applies_success_patch(
    tmp_path, fake_llm, fake_device
):
    # The card names its target ('Tap "Next"'), so it compiles without an
    # LLM round trip; the queue starts at the post-plan summarize call.
    fake_llm.responses = [
        _batch(True, True),
        "Notes list with a plus button",
        {"satisfied": True},
        {"achieved": True},
    ]
    pipeline = _pipeline(
        tmp_path, fake_llm, fake_device, cards=[_card("create_note")]
    )

    summary = pipeline.run_goal("create a note", "Notes list")

    assert summary["success"] is True
    assert summary["goal_success"] is True
    assert summary["rounds"] == 1
    assert summary["path"] == ["create_note"]
    stored = pipeline.card_store.load("create_note")
    assert stored.success_count == 1
    assert stored.attempt_count == 1


def test_run_goal_completes_missing_capability_and_retries(
    tmp_path, fake_llm, fake_device, probe_trace
):
    fake_llm.responses = [
        {"gap": "need create_note"},
        {
            "capabilities": [
                {
                    "name": "create_note",
                    "intent": "create a note",
                    "probe": ["tap +"],
                    "confidence": 0.9,
                }
            ]
        },
        CARD_MARKDOWN,
        _batch(True, True),
        {"steps": [{"action": "click", "target": "text=Next"}]},
        "Notes list with a plus button",
        {"satisfied": True},
        {"achieved": True},
    ]
    probe = FakeProbe()
    probe.trace = probe_trace
    pipeline = _pipeline(
        tmp_path, fake_llm, fake_device, probe=probe
    )

    summary = pipeline.run_goal(
        "create a note", "Notes list", max_rounds=2
    )

    assert summary["success"] is True
    assert summary["rounds"] == 2
    assert "create_note" in pipeline.card_store.all()


def test_run_goal_reports_failure_when_no_plan_and_no_completion(
    tmp_path, fake_llm, fake_device
):
    fake_llm.responses = [{"gap": None}, {"gap": None}]
    pipeline = _pipeline(tmp_path, fake_llm, fake_device)

    summary = pipeline.run_goal("create a note", "Notes list", max_rounds=2)

    assert summary["success"] is False
    assert summary["rounds"] == 2
    assert summary["path"] == []


def test_device_probe_compiles_and_executes(fake_llm, fake_device):
    fake_llm.responses = [
        {"steps": [{"action": "click", "target": "text=Attach"}]}
    ]
    probe = DeviceProbe(fake_device, StepCompiler(fake_llm))
    capability = MissingCapability(
        name="attach_photo",
        intent="attach a photo",
        probe=["Tap Attach"],
    )

    trace = probe.run(capability, "note open")

    assert trace is not None
    assert trace.trace_id.startswith("probe-")
    assert trace.steps[0].action == "click"
    assert fake_device.calls == [("click", "text=Attach", "")]


def test_device_probe_grounds_each_step_in_the_screen_it_runs_on(
    fake_llm, fake_device
):
    """A probe is a walk, not a script written in advance.

    A capability's later steps act on screens that do not exist yet ("open
    the dialog", then "tap OK" inside it).  Compiling all of them against
    the starting screen names controls that are not there, and aborting on
    the first miss discards the walk before the screen it needed appears.
    Each step is compiled against the screen it will actually run on.
    """
    fake_device.states = ["home", "menu open", "dialog open"]
    fake_llm.responses = [
        {"steps": [{"action": "click", "target": "text=Menu"}]},
        {"steps": [{"action": "click", "target": "text=New"}]},
    ]
    probe = DeviceProbe(fake_device, StepCompiler(fake_llm))
    capability = MissingCapability(
        name="create_type",
        intent="create a type",
        probe=["Tap Menu", "Tap New"],
    )

    trace = probe.run(capability, "home")

    assert trace is not None
    assert [step.target for step in trace.steps] == ["text=Menu", "text=New"]
    # The second step's prompt sees the screen the first step produced.
    assert "menu open" in fake_llm.prompts[1]


def test_device_probe_keeps_what_it_learned_before_a_miss(
    fake_llm, fake_device
):
    """A miss ends the walk, not the evidence: the steps that ran are a
    trace of real behavior and are returned."""
    fake_device.states = ["home"]
    fake_device.action_results = [True, False]
    fake_llm.responses = [
        {"steps": [{"action": "click", "target": "text=Menu"}]},
        {"steps": [{"action": "click", "target": "text=Missing"}]},
    ]
    probe = DeviceProbe(fake_device, StepCompiler(fake_llm))

    trace = probe.run(
        MissingCapability(name="x", probe=["Tap Menu", "Tap Missing"]),
        "home",
    )

    assert trace is not None
    assert [step.success for step in trace.steps] == [True, False]


def test_device_probe_with_no_probe_plan_returns_none(fake_llm, fake_device):
    probe = DeviceProbe(fake_device, StepCompiler(fake_llm))
    capability = MissingCapability(name="attach_photo", probe=[])

    assert probe.run(capability, "note open") is None
    assert fake_llm.calls == 0
    assert fake_device.calls == []


def test_journal_reason_names_the_trace_and_what_it_added(
    tmp_path, fake_llm, fake_device, sample_trace
):
    fake_llm.responses = [
        {"episodes": [{"start": 0, "end": 1, "name": "create_note"}]},
        CARD_MARKDOWN,
    ]
    pipeline = _pipeline(tmp_path, fake_llm, fake_device)

    pipeline.mine_trace(sample_trace)
    pipeline.build_graph([])

    reasons = [entry["reason"] for entry in pipeline.store.journal()]
    assert reasons == [
        "mined trace t1 -> create_note",
        "semantic edges over 1 card",
    ]


def test_mining_the_same_trace_twice_adds_its_function_once(
    tmp_path, fake_llm, fake_device, sample_trace
):
    """A trace is evidence, and the same evidence is applied once.

    The recorded omninotes graph mined omni-merge twice, eighteen minutes
    apart, and ended up holding merge_notes and merge_two_notes -- one
    function written under two names.
    """
    fake_llm.responses = [
        {"episodes": [{"start": 0, "end": 1, "name": "create_note"}]},
        CARD_MARKDOWN,
        {"episodes": [{"start": 0, "end": 1, "name": "create_note_again"}]},
        CARD_MARKDOWN.replace("# create_note", "# create_note_again"),
    ]
    pipeline = _pipeline(tmp_path, fake_llm, fake_device)

    first = pipeline.mine_trace(sample_trace)
    used = fake_llm.calls
    again = pipeline.mine_trace(sample_trace)

    assert first.new_cards
    assert again.new_cards == []
    assert fake_llm.calls == used
    assert sorted(pipeline.store.load().cards) == ["create_note"]


def test_a_trace_whose_steps_changed_is_mined_again(
    tmp_path, fake_llm, fake_device, sample_trace
):
    """Re-collected evidence is new evidence, not a repeat."""
    from dataclasses import replace

    from specfcg.models import Step

    fake_llm.responses = [
        {"episodes": [{"start": 0, "end": 1, "name": "create_note"}]},
        CARD_MARKDOWN,
        {"episodes": [{"start": 0, "end": 1, "name": "create_note_again"}]},
        CARD_MARKDOWN.replace("# create_note", "# create_note_again"),
    ]
    pipeline = _pipeline(tmp_path, fake_llm, fake_device)
    pipeline.mine_trace(sample_trace)
    used = fake_llm.calls

    changed = replace(
        sample_trace,
        steps=sample_trace.steps + [Step(action="click", target="text=Share")],
    )
    pipeline.mine_trace(changed)

    assert fake_llm.calls > used
    assert sorted(pipeline.store.load().cards) == [
        "create_note",
        "create_note_again",
    ]

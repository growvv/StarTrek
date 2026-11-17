from specfcg.completion.completer import CapabilityCompleter
from specfcg.models import Goal


def _completer(
    fake_llm, graph_store, card_miner, edge_builder, fake_probe, **kwargs
):
    return CapabilityCompleter(
        fake_llm,
        graph_store,
        card_miner,
        edge_builder,
        fake_probe,
        **kwargs,
    )


def test_no_gap_returns_none(
    fake_llm, graph_store, card_miner, edge_builder, fake_probe
):
    fake_llm.responses = [{"gap": None}]
    assert (
        _completer(
            fake_llm, graph_store, card_miner, edge_builder, fake_probe
        ).complete(Goal("already reachable"), "state")
        is None
    )


def test_complete_adds_card_on_successful_probe(
    fake_llm,
    graph_store,
    card_miner,
    edge_builder,
    fake_probe,
    probe_trace,
):
    fake_llm.responses = [
        {"gap": "need attach_photo"},
        {
            "capabilities": [
                {
                    "name": "attach_photo",
                    "intent": "attach a photo",
                    "preconditions": "note exists",
                    "postconditions": "photo attached",
                    "inputs": ["note", "photo"],
                    "probe": ["open note", "tap attach"],
                    "confidence": 0.8,
                }
            ]
        },
        "# attach_photo\n\n**Intent**: attach a photo\n**Inputs**: note, photo\n"
        "**Preconditions**: note exists\n**Postconditions**: photo attached\n"
        "**Effects/Outputs**: note has photo\n**Steps**:\n1. Tap attach\n"
        "**Evidence**: traces t9; 1/1 successes",
        {"edges": []},
    ]
    fake_probe.trace = probe_trace
    patch = _completer(
        fake_llm, graph_store, card_miner, edge_builder, fake_probe
    ).complete(Goal("attach a photo"), "state")
    assert patch is not None
    assert any(card.name == "attach_photo" for card in patch.new_cards)


def test_complete_adds_semantic_edges_for_new_card(
    fake_llm,
    graph_store,
    card_miner,
    edge_builder,
    fake_probe,
    probe_trace,
):
    fake_llm.responses = [
        {"gap": "need attach_photo"},
        {
            "capabilities": [
                {
                    "name": "attach_photo",
                    "intent": "attach a photo",
                    "probe": ["tap attach"],
                }
            ]
        },
        "# attach_photo\n\n**Intent**: attach a photo\n**Inputs**: none\n"
        "**Preconditions**: note exists\n**Postconditions**: photo attached\n"
        "**Effects/Outputs**: photo attached\n**Steps**:\n1. Tap attach\n"
        "**Evidence**: traces t9; 1/1 successes",
        {
            "edges": [
                {
                    "from": "create_note",
                    "to": "attach_photo",
                    "type": "enables",
                    "description": "a note enables attaching a photo",
                }
            ]
        },
    ]
    fake_probe.trace = probe_trace

    patch = _completer(
        fake_llm, graph_store, card_miner, edge_builder, fake_probe
    ).complete(Goal("attach a photo"), "state")

    assert patch is not None
    assert any(
        edge["from"] == "create_note"
        and edge["to"] == "attach_photo"
        and edge["type"] == "enables"
        for edge in patch.edge_updates
    )


def test_complete_merges_existing_card_on_name_collision(
    fake_llm,
    graph_store,
    card_miner,
    edge_builder,
    fake_probe,
    probe_trace,
):
    fake_llm.responses = [
        {"gap": "need create_note"},
        {
            "capabilities": [
                {
                    "name": "create_note",
                    "intent": "create a note",
                    "probe": ["tap plus"],
                }
            ]
        },
        "# create_note\n\n**Intent**: Create a note.\n**Inputs**: none\n"
        "**Preconditions**: note exists\n**Postconditions**: created\n"
        "**Effects/Outputs**: note\n**Steps**:\n1. Tap plus\n"
        "**Evidence**: traces t9; 1/1 successes",
        {"edges": []},
    ]
    fake_probe.trace = probe_trace

    patch = _completer(
        fake_llm, graph_store, card_miner, edge_builder, fake_probe
    ).complete(Goal("create a note"), "state")

    assert patch is not None
    assert patch.new_cards == []
    update = next(
        item
        for item in patch.card_updates
        if item["name"] == "create_note"
    )
    assert update["fields"]["evidence"] == ["t1", "t2", "t9"]
    assert update["fields"]["success_count"] == 3
    assert update["fields"]["attempt_count"] == 4


def test_budget_limits_hypotheses(
    fake_llm, graph_store, card_miner, edge_builder, fake_probe
):
    fake_llm.responses = [
        {"gap": "need x"},
        {
            "capabilities": [
                {"name": "x", "intent": "do x"},
                {"name": "y", "intent": "do y"},
            ]
        },
    ]
    fake_probe.trace = None
    assert (
        _completer(
            fake_llm,
            graph_store,
            card_miner,
            edge_builder,
            fake_probe,
            max_hypotheses=1,
            max_probes=1,
        ).complete(Goal("x"), "state")
        is None
    )
    assert len(fake_probe.calls) == 1
    assert (graph_store.root / "completion" / "negative.jsonl").exists()


def test_empty_hypotheses_returns_none(
    fake_llm, graph_store, card_miner, edge_builder, fake_probe
):
    fake_llm.responses = [{"gap": "need x"}, {"capabilities": []}]
    assert (
        _completer(
            fake_llm, graph_store, card_miner, edge_builder, fake_probe
        ).complete(Goal("x"), "state")
        is None
    )


def test_hypotheses_probe_may_walk_onto_later_screens(
    fake_llm, graph_store, card_miner, edge_builder, fake_probe
):
    """The probe executes step by step and grounds each step on the screen
    it runs on, so a later step may name a control that only appears after
    an earlier one.  The prompt must say so, or the model confines itself to
    controls already visible and proposes one-step probes."""
    fake_llm.responses = [{"gap": "need checklist"}, {"capabilities": []}]

    _completer(
        fake_llm, graph_store, card_miner, edge_builder, fake_probe
    )._hypothesize(
        "need checklist",
        Goal("create a checklist note"),
        2,
        "FloatingActionButton text='文本注释'",
    )

    prompt = fake_llm.prompts[-1]
    assert "first step" in prompt.lower()
    assert "later step" in prompt.lower()


def test_hypotheses_are_grounded_in_the_observed_screen(
    fake_llm, graph_store, card_miner, edge_builder, fake_probe
):
    """The hypothesis step must see the screen it is proposing a probe for.

    Without the state the model invents English labels ("Take a note…") for
    an app whose build shows Chinese ones (文本注释), and every probe fails on
    a selector that does not exist.
    """
    fake_llm.responses = [{"gap": "need checklist"}, {"capabilities": []}]

    _completer(
        fake_llm, graph_store, card_miner, edge_builder, fake_probe
    )._hypothesize(
        "need checklist",
        Goal("create a checklist note"),
        2,
        "ImageButton desc='抽屉打开'\nFloatingActionButton text='文本注释'",
    )

    assert "文本注释" in fake_llm.prompts[-1]

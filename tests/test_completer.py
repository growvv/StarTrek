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

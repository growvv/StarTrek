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
    ]
    fake_probe.trace = probe_trace
    patch = _completer(
        fake_llm, graph_store, card_miner, edge_builder, fake_probe
    ).complete(Goal("attach a photo"), "state")
    assert patch is not None
    assert any(card.name == "attach_photo" for card in patch.new_cards)


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

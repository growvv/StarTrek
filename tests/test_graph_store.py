from dataclasses import replace

from specfcg.cards.store import CardStore
from specfcg.graph.store import GraphStore
from specfcg.models import GraphPatch


def _store(tmp_path, sample_card, another_card):
    cards = CardStore(tmp_path)
    cards.save(sample_card)
    cards.save(another_card)
    return GraphStore(tmp_path, cards)


def test_duplicate_edge_is_deduped(tmp_path, sample_card, another_card):
    cards = CardStore(tmp_path)
    cards.save(sample_card)
    cards.save(another_card)
    store = GraphStore(tmp_path, cards)
    store.apply_patch(
        GraphPatch(
            edge_updates=[
                {
                    "from": sample_card.name,
                    "to": another_card.name,
                    "type": "enables",
                    "action": "add",
                    "description": "d1",
                    "evidence": ["t1"],
                }
            ]
        )
    )
    store.apply_patch(
        GraphPatch(
            edge_updates=[
                {
                    "from": sample_card.name,
                    "to": another_card.name,
                    "type": "enables",
                    "action": "add",
                    "description": "d2",
                    "evidence": ["t2"],
                }
            ]
        )
    )
    edges = store.edges()
    assert len(edges) == 1
    assert edges[0].description == "d2"
    assert edges[0].evidence == ["t1", "t2"]


def test_backup_and_restore(tmp_path, sample_card):
    cards = CardStore(tmp_path)
    cards.save(sample_card)
    store = GraphStore(tmp_path, cards)
    version = store.backup()
    store.apply_patch(
        GraphPatch(
            card_updates=[
                {"name": sample_card.name, "fields": {"Intent": "changed"}}
            ]
        )
    )
    store.restore(version)
    assert store.load().cards[sample_card.name].intent == sample_card.intent


def test_edge_with_unknown_endpoint_is_skipped(
    tmp_path, sample_card, another_card
):
    store = _store(tmp_path, sample_card, another_card)
    store.apply_patch(
        GraphPatch(
            edge_updates=[
                {
                    "from": "missing",
                    "to": another_card.name,
                    "type": "enables",
                    "action": "add",
                }
            ]
        )
    )
    assert store.edges() == []


def test_uncoercible_card_update_field_is_skipped(tmp_path, sample_card):
    cards = CardStore(tmp_path)
    cards.save(sample_card)
    store = GraphStore(tmp_path, cards)

    store.apply_patch(
        GraphPatch(
            card_updates=[
                {
                    "name": sample_card.name,
                    "fields": {
                        "success_count": "many",
                        "evidence": ["t3"],
                    },
                }
            ]
        )
    )

    card = cards.load(sample_card.name)
    assert card.success_count == sample_card.success_count
    assert "t3" in card.evidence


def test_neighbors_orders_by_type_priority(
    tmp_path, sample_card, another_card
):
    store = _store(tmp_path, sample_card, another_card)
    for edge_type in ("sequence", "enables", "dataflow"):
        store.apply_patch(
            GraphPatch(
                edge_updates=[
                    {
                        "from": sample_card.name,
                        "to": another_card.name,
                        "type": edge_type,
                        "action": "add",
                    }
                ]
            )
        )
    assert [edge.type for edge in store.neighbors(sample_card.name)] == [
        "enables",
        "dataflow",
        "sequence",
    ]


def test_apply_patch_appends_a_journal_entry(tmp_path, sample_card, another_card):
    store = _store(tmp_path, sample_card, another_card)

    store.apply_patch(
        GraphPatch(
            edge_updates=[
                {
                    "from": sample_card.name,
                    "to": another_card.name,
                    "type": "enables",
                    "action": "add",
                    "description": "d1",
                }
            ],
            reason="mined trace t3",
        )
    )

    journal = store.journal()
    assert len(journal) == 1
    entry = journal[0]
    assert entry["reason"] == "mined trace t3"
    assert entry["cards_added"] == 0
    assert entry["edges_added"] == 1
    assert entry["cards_total"] == 2
    assert entry["edges_total"] == 1
    assert entry["edge_list"] == [
        {"from": sample_card.name, "to": another_card.name, "type": "enables"}
    ]


def test_journal_records_new_cards_and_updates(tmp_path, sample_card, another_card):
    store = _store(tmp_path, sample_card, another_card)
    third = replace(another_card, name="archive_note")

    store.apply_patch(GraphPatch(new_cards=[third], reason="mined trace t4"))
    store.apply_patch(
        GraphPatch(
            card_updates=[
                {"name": sample_card.name, "fields": {"Intent": "changed"}}
            ],
            reason="refine after failure",
        )
    )

    journal = store.journal()
    assert [entry["reason"] for entry in journal] == [
        "mined trace t4",
        "refine after failure",
    ]
    assert journal[0]["cards_added"] == 1
    assert journal[0]["cards_total"] == 3
    assert journal[1]["cards_updated"] == 1
    assert journal[1]["cards_added"] == 0


def test_journal_is_empty_before_any_patch(tmp_path, sample_card):
    cards = CardStore(tmp_path)
    cards.save(sample_card)
    assert GraphStore(tmp_path, cards).journal() == []

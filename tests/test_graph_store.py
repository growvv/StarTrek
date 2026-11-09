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

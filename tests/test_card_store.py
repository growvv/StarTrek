from specfcg.cards.store import CardStore


def test_card_store_saves_and_loads(tmp_path, sample_card):
    store = CardStore(tmp_path)
    store.save(sample_card)
    assert store.load(sample_card.name) == sample_card


def test_malformed_card_file_is_skipped(tmp_path, sample_card):
    store = CardStore(tmp_path)
    store.save(sample_card)
    (tmp_path / "cards" / "broken.md").write_text("# broken", encoding="utf-8")
    assert list(store.all()) == [sample_card.name]

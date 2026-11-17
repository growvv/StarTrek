from dataclasses import replace

from specfcg.models import Goal
from specfcg.planner.retrieval import CardRetriever


def test_retrieve_returns_all_when_small(fake_llm, two_cards):
    assert set(
        CardRetriever(fake_llm).retrieve(
            Goal("create and share a note"), two_cards
        )
    ) == {"create_note", "share_note"}


def test_retrieve_prefilters_then_confirms(fake_llm, two_cards):
    fake_llm.responses = [{"keep": ["share_note"]}]
    assert CardRetriever(fake_llm, top_k=1).retrieve(
        Goal("share a note"), two_cards
    ) == ["share_note"]


def test_retrieve_falls_back_on_malformed_confirmation(fake_llm, two_cards):
    fake_llm.responses = ["not json"]
    assert CardRetriever(fake_llm, top_k=1).retrieve(
        Goal("share a note"), two_cards
    ) == ["share_note"]


def test_retrieve_keeps_a_card_that_matches_the_goal_verbatim(
    fake_llm, two_cards
):
    """The LLM filter may add semantic recall; it must not delete a card
    whose own name and intent share the goal's words.  A rename task names
    "rename" and the card is called rename_file; dropping it leaves the
    planner with no route the graph already had."""
    cards = dict(two_cards)
    cards["rename_file"] = replace(
        cards["create_note"],
        name="rename_file",
        intent="Rename a file to a new name.",
    )
    fake_llm.responses = [{"keep": ["create_note", "share_note"]}]

    kept = CardRetriever(fake_llm, top_k=2).retrieve(
        Goal("rename the file a.txt to b.txt"), cards
    )

    assert "rename_file" in kept


def test_retrieve_falls_back_when_confirmation_drops_all(
    fake_llm, two_cards
):
    fake_llm.responses = [{"keep": ["missing"]}]
    assert CardRetriever(fake_llm, top_k=1).retrieve(
        Goal("share a note"), two_cards
    ) == ["share_note"]

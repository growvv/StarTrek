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


def test_retrieve_falls_back_when_confirmation_drops_all(
    fake_llm, two_cards
):
    fake_llm.responses = [{"keep": ["missing"]}]
    assert CardRetriever(fake_llm, top_k=1).retrieve(
        Goal("share a note"), two_cards
    ) == ["share_note"]

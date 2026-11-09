from specfcg.cards.store import CardStore
from specfcg.maintainer.miner import CardMiner


def test_segment_returns_llm_boundaries(tmp_path, fake_llm, sample_trace):
    fake_llm.responses = [
        {
            "episodes": [
                {
                    "start": 0,
                    "end": 1,
                    "name": "create_note",
                    "intent": "create a note",
                },
                {
                    "start": 2,
                    "end": 3,
                    "name": "share_note",
                    "intent": "share a note",
                },
            ]
        }
    ]
    segments = CardMiner(fake_llm, CardStore(tmp_path)).segment(sample_trace)
    assert [s["name"] for s in segments] == ["create_note", "share_note"]


def test_segment_invalid_boundaries_falls_back_to_single_episode(
    tmp_path, fake_llm, sample_trace
):
    fake_llm.responses = [{"episodes": [{"start": 5, "end": 99}]}]
    segments = CardMiner(fake_llm, CardStore(tmp_path)).segment(sample_trace)
    assert len(segments) == 1
    assert segments[0]["start"] == 0


def test_mine_empty_trace_returns_empty_patch(tmp_path, fake_llm, empty_trace):
    patch = CardMiner(fake_llm, CardStore(tmp_path)).mine(empty_trace)
    assert patch.new_cards == [] and patch.segments == []


def test_mine_single_step_trace_produces_card(
    tmp_path, fake_llm, single_step_trace
):
    fake_llm.responses = [
        {
            "episodes": [
                {
                    "start": 0,
                    "end": 0,
                    "name": "open_app",
                    "intent": "open the app",
                }
            ]
        },
        "# open_app\n\n**Intent**: open the app\n**Inputs**: none\n"
        "**Preconditions**: app closed\n**Postconditions**: app is open\n"
        "**Effects/Outputs**: none\n**Steps**:\n1. Tap the icon\n"
        "**Evidence**: traces t1; 1/1 successes",
    ]
    patch = CardMiner(fake_llm, CardStore(tmp_path)).mine(single_step_trace)
    assert patch.new_cards[0].name == "open_app"


def test_draft_falls_back_on_malformed_markdown(
    tmp_path, fake_llm, sample_trace
):
    fake_llm.responses = ["not a card"]
    miner = CardMiner(fake_llm, CardStore(tmp_path))
    episode = {
        "start": 0,
        "end": 1,
        "name": "create_note",
        "intent": "create a note",
    }
    card = miner.draft(episode, sample_trace)
    assert card.name == "create_note"
    assert card.steps == ["click text=+", "input text=Title"]


def test_mine_merges_existing_card_evidence(
    tmp_path, fake_llm, sample_trace, sample_card
):
    cards = CardStore(tmp_path)
    cards.save(sample_card)
    fake_llm.responses = [
        {
            "episodes": [
                {
                    "start": 0,
                    "end": 3,
                    "name": sample_card.name,
                    "intent": "create a note",
                }
            ]
        },
        "# create_note\n\n**Intent**: create a note\n**Inputs**: title\n"
        "**Preconditions**: on list\n**Postconditions**: note exists\n"
        "**Effects/Outputs**: note\n**Steps**:\n1. Tap +\n"
        "**Evidence**: traces t1; 1/1 successes",
    ]
    patch = CardMiner(fake_llm, cards).mine(sample_trace)
    assert patch.new_cards == []
    assert patch.updates[0]["name"] == sample_card.name
    assert "t1" in patch.updates[0]["fields"]["evidence"]
    assert (
        patch.updates[0]["fields"]["attempt_count"]
        == sample_card.attempt_count + 1
    )

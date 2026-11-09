import pytest

from specfcg.cards.parser import CardParseError, parse_card, render_card


def test_card_round_trip(sample_card):
    assert parse_card(render_card(sample_card)) == sample_card


def test_parse_card_missing_heading_raises():
    with pytest.raises(CardParseError):
        parse_card("# broken\n\n**Intent**: only intent")


def test_parse_evidence_counts(sample_card):
    card = parse_card(render_card(sample_card))
    assert card.success_count == 2
    assert card.attempt_count == 3
    assert card.evidence == ["t1", "t2"]

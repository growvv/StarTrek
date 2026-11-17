from __future__ import annotations

import pytest

from specfcg.benchmark.granularity import card_surface, granularity
from specfcg.models import FunctionCard


def _card(name: str, *steps: str) -> FunctionCard:
    return FunctionCard(
        name=name,
        intent=f"do {name}",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=list(steps),
    )


NOTE_TITLE = "it.feio.android.omninotes.foss:id/note_title"


def test_two_cards_that_tap_the_same_control_are_one_node():
    """Card names are invented per trace; the behaviour is what defines a node."""
    first = _card(
        "open_note",
        "Tap the note title text matching {note_title} in the notes list "
        f"(`TextView id='{NOTE_TITLE}'`).",
    )
    second = _card(
        "open_note_from_list",
        "On the notes list screen, tap the note title {note_title} "
        f"(resource id `{NOTE_TITLE}`).",
    )

    assert card_surface(first) == card_surface(second)
    report = granularity({"open_note": first, "open_note_from_list": second})
    assert report.duplicate_groups == [
        ["open_note", "open_note_from_list"]
    ]
    assert report.score == 0.5


def test_the_value_bound_to_a_control_is_a_parameter_not_a_behaviour():
    """Two cards that tap the same control differ only in the value bound."""
    plain = _card(
        "open_note",
        "Tap the note title text matching {note_title} in the notes list "
        f"(`TextView id='{NOTE_TITLE}'`).",
    )
    bound = _card(
        "open_note_by_title",
        "Tap the visible text {note_title} on TextView "
        f"id='{NOTE_TITLE}' within the clickable note row FrameLayout "
        "id='it.feio.android.omninotes.foss:id/root'.",
    )

    assert card_surface(plain) == card_surface(bound)


def test_a_literal_label_identifies_the_control_it_names():
    """Only a caller-supplied value is a parameter.

    Archive and pin are two menu rows that share one generic resource id and
    differ only in their visible label.  Stripping the label would make two
    different functions one node -- the mistake this measure exists to
    avoid, in the other direction.
    """
    archive = _card(
        "archive_note",
        "Tap the '归档' menu item (TextView id 'pkg:id/title') "
        "in the opened overflow menu.",
    )
    pin = _card(
        "pin_note",
        "Click the TextView with visible label '置顶笔记' and id "
        "'pkg:id/title' to pin {note}.",
    )

    assert card_surface(archive) != card_surface(pin)
    assert granularity({"archive_note": archive, "pin_note": pin}).score == 1.0


def test_a_different_control_is_a_different_node():
    tap_title = _card(
        "open_note", f"Tap the note title ({NOTE_TITLE})."
    )
    tap_share = _card(
        "share_note", "Tap the share action (`id/omninotes:id/menu_share`)."
    )

    report = granularity({"open_note": tap_title, "share_note": tap_share})

    assert report.duplicate_groups == []
    assert report.score == 1.0


def test_three_cards_for_one_control_count_as_one_node():
    cards = {
        f"open_note_{index}": _card(
            f"open_note_{index}", f"Tap the note title (`{NOTE_TITLE}`)."
        )
        for index in range(3)
    }

    report = granularity(cards)

    assert report.distinct == 1
    assert report.score == pytest.approx(1 / 3)


def test_a_card_with_no_concrete_control_is_left_out_of_both_sides():
    """The denominator is the set the numerator counts, not every card.

    A step the compiler cannot resolve without the model has no behaviour
    surface to compare, so it is neither a node nor a duplicate.  Counting
    it in the denominator would report a score for a comparison that was
    never made.
    """
    concrete = _card("open_note", f"Tap the note title (`{NOTE_TITLE}`).")
    prose = _card(
        "change_theme", "Open the settings screen and pick a different theme."
    )

    report = granularity({"open_note": concrete, "change_theme": prose})

    assert report.cards == 2
    assert report.measured == 1
    assert report.score == 1.0


def test_a_graph_whose_cards_do_not_compile_earns_no_score():
    report = granularity(
        {"change_theme": _card("change_theme", "Change how the app looks.")}
    )

    assert report.measured == 0
    assert report.score is None

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


def test_parse_evidence_ignores_backticked_resource_ids_in_prose():
    card = parse_card(
        """# create_note

**Intent**: Create a note.
**Inputs**: none
**Preconditions**: On the list.
**Postconditions**: A note exists.
**Effects/Outputs**: A note card.
**Steps**:
1. Tap the button `app:id/fab`.
**Evidence**: Trace evidence: `omninotes-create-note-2`. Flow uses `app:id/fab` and `app:id/title`; 1/1 successes
"""
    )

    assert card.evidence == ["omninotes-create-note-2"]


def test_parse_evidence_extracts_backticked_trace_id_from_prose():
    card = parse_card(
        """# create_note

**Intent**: Create a note.
**Inputs**: none
**Preconditions**: On the list.
**Postconditions**: A note exists.
**Effects/Outputs**: A note card.
**Steps**:
1. Tap the plus button
**Evidence**: Trace evidence: `omninotes-create-note-2`. The trace shows the flow; 1/1 successes
"""
    )

    assert card.evidence == ["omninotes-create-note-2"]
    assert card.success_count == 1
    assert card.attempt_count == 1


def test_parse_card_accepts_bullet_inputs_with_backticks():
    card = parse_card(
        """# create_note

**Intent**: Create a note.
**Inputs**:
- `title`: the note title, shown in the list
- `content` (optional): the note body
**Preconditions**: On the list.
**Postconditions**: A note exists.
**Effects/Outputs**: A new note card.
**Steps**:
1. Tap the plus button
**Evidence**: traces t1; 1/1 successes
"""
    )

    assert card.inputs == [
        "`title`: the note title, shown in the list",
        "`content` (optional): the note body",
    ]


def test_parse_card_keeps_commas_inside_a_single_bullet_input():
    card = parse_card(
        """# archive_note

**Intent**: Archive a note.
**Inputs**:
- target_note (required): visible title, matched through `app:id/note_title`
**Preconditions**: On the list.
**Postconditions**: The note is archived.
**Effects/Outputs**: The note leaves the list.
**Steps**:
1. Tap the note
**Evidence**: traces t1; 1/1 successes
"""
    )

    assert card.inputs == [
        "target_note (required): visible title, matched through "
        "`app:id/note_title`"
    ]


def test_parse_card_accepts_section_headings_without_colon():
    card = parse_card(
        """# create_note

**Intent**

Create a note with a title.

**Inputs**

- title: Trip

**Preconditions**

On the notes list.

**Postconditions**

A note exists.

**Effects/Outputs**

A new note card.

**Steps**

1. Tap the plus button
2. Enter the title

**Evidence**

Trace: t1; 1/1 successes
"""
    )

    assert card.name == "create_note"
    assert card.intent == "Create a note with a title."
    assert card.preconditions == "On the notes list."
    assert card.steps == ["Tap the plus button", "Enter the title"]
    assert card.evidence == ["t1"]
    assert card.success_count == 1
    assert card.attempt_count == 1

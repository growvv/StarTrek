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

**Evidence**

Trace: t1; 1/1 successes
"""
    )

    assert card.name == "create_note"
    assert card.intent == "Create a note with a title."
    assert card.preconditions == "On the notes list."
    assert card.evidence == ["t1"]
    assert card.success_count == 1
    assert card.attempt_count == 1


def test_parse_inputs_does_not_split_a_description_at_its_commas():
    """One declaration is one input, however its description is punctuated.

    The card writer emits 'name (required): description, with a comma' on a
    single line.  Splitting that line at every comma invents a required
    input called 'including' (Amaze create_new_empty_file) or 'used' (a
    parent-folder description), and the binder then demands a value the card
    never had -- which turns a valid plan into no_plan.
    """
    card = parse_card(
        """# create_new_empty_file

**Intent**: Create a file named {file_name}.
**Inputs**: file_name (required): Name to assign to the new empty file, including any desired extension.
**Preconditions**: On a folder listing.
**Postconditions**: The file exists.
**Effects/Outputs**: A new file.
**Evidence**: traces t1; 1/1 successes
"""
    )

    assert card.inputs == [
        "file_name (required): Name to assign to the new empty file, "
        "including any desired extension."
    ]


def test_parse_inputs_splits_a_plain_list_of_names():
    """Without a description, commas do separate inputs."""
    card = parse_card(
        """# switch_activity

**Intent**: Switch activity.
**Inputs**: current_activity (required), target_activity (required)
**Preconditions**: On the diary.
**Postconditions**: Switched.
**Effects/Outputs**: None.
**Evidence**: traces t1; 1/1 successes
"""
    )

    assert card.inputs == [
        "current_activity (required)",
        "target_activity (required)",
    ]


def test_parse_card_accepts_a_colon_inside_the_bold_heading():
    """``**Intent:** ...`` is the same heading as ``**Intent**: ...``.

    A model that writes the colon inside the bold markers produces a card
    whose every section is unreadable, so the whole card silently degrades to
    the fallback -- a card with no intent and no preconditions.
    """
    card = parse_card(
        """# create_note

**Intent:** Create a note.
**Inputs:** none
**Preconditions:** On the notes list.
**Postconditions:** A note exists.
**Effects/Outputs:** A note card.
**Evidence:** traces t1; 1/1 successes
"""
    )

    assert card.intent == "Create a note."
    assert card.evidence == ["t1"]


def test_card_with_a_steps_section_is_rejected():
    """A card that still carries recorded taps must fail loudly.

    Task F removes ``steps`` from the card: the card names what a function
    does, never how it was done once.  An old card whose Steps section is
    silently folded into the preceding section would keep its recorded taps
    alive as prose, so the parser refuses it instead.
    """
    text = (
        "# create_note\n\n**Intent**: Create a note.\n"
        "**Inputs**: none\n**Preconditions**: The list is open.\n"
        "**Postconditions**: The note exists.\n**Effects/Outputs**: none\n"
        "**Steps**:\n1. Tap '+'. 2. Tap 'Save'.\n**Evidence**: traces t1\n"
    )
    with pytest.raises(CardParseError, match="Steps"):
        parse_card(text)


def test_rendered_card_round_trips_without_steps(sample_card):
    assert "**Steps**" not in render_card(sample_card)
    assert parse_card(render_card(sample_card)) == sample_card

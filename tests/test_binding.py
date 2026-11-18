from dataclasses import replace

from specfcg.models import Goal
from specfcg.planner.binding import ParamBinder, _param_name


def test_bind_uses_goal_values_and_prior_outputs(fake_llm, two_cards):
    fake_llm.responses = [
        {
            "bindings": {
                "note": "$create_note.output",
                "channel": "email",
            }
        }
    ]
    out = ParamBinder(fake_llm).bind(
        two_cards["share_note"],
        Goal("share via email"),
        "note exists",
        {"create_note.output": "Trip"},
    )
    assert out == {"note": "Trip", "channel": "email"}


def test_bind_prompt_makes_the_subgoal_authoritative(fake_llm, sample_card):
    """When a card runs twice in one plan, the second instance's subgoal names
    its own values; ambient prior outputs must not override them."""
    fake_llm.responses = [
        {"bindings": {"title": "Keep this one", "content": ""}}
    ]

    ParamBinder(fake_llm).bind(
        sample_card,
        Goal("Create a second note titled 'Keep this one'"),
        "notes list",
        {"create_note.title": "Temporary memo"},
    )

    prompt = fake_llm.prompts[0]
    assert "authoritative" in prompt
    assert "prior output" in prompt


def test_bind_missing_required_returns_none(fake_llm, two_cards):
    fake_llm.responses = [{"bindings": {}}, {"bindings": {}}]
    assert (
        ParamBinder(fake_llm).bind(
            two_cards["share_note"], Goal("share"), "state", {}
        )
        is None
    )


def test_bind_unresolved_reference_returns_none(fake_llm, two_cards):
    fake_llm.responses = [
        {"bindings": {"note": "$missing.output", "channel": "email"}},
        {"bindings": {"note": "$missing.output", "channel": "email"}},
    ]
    assert (
        ParamBinder(fake_llm).bind(
            two_cards["share_note"], Goal("share"), "state", {}
        )
        is None
    )


def test_bind_normalizes_input_descriptions(
    fake_llm, sample_card, two_cards
):
    card = replace(
        two_cards["share_note"],
        inputs=["note (text)", "channel (text, optional)"],
    )
    fake_llm.responses = [
        {"bindings": {"note": "Trip", "channel": "email"}}
    ]
    out = ParamBinder(fake_llm).bind(card, Goal("share"), "state", {})
    assert out == {"note": "Trip", "channel": "email"}


def test_param_name_strips_markdown_and_description():
    assert _param_name("`title`: the note title") == "title"
    assert _param_name("`content` (optional): the note body") == "content"
    assert _param_name("plain_name (text)") == "plain_name"


def test_bind_accepts_an_explicit_empty_value(fake_llm, sample_card):
    """An empty value is an answer, not a missing one.

    The goal names a title and says nothing about content; the card declares
    content required.  The model's deliberate empty binding is the only
    correct answer, and rejecting it abandons a plan that would have run.
    What is missing is a key the model never returned, or a reference it
    could not resolve.
    """
    card = replace(
        sample_card, inputs=["title (required)", "content (required)"]
    )
    fake_llm.responses = [{"bindings": {"title": "Grocery list", "content": ""}}]

    out = ParamBinder(fake_llm).bind(
        card, Goal("Create a note titled Grocery list"), "list", {}
    )

    assert out == {"title": "Grocery list", "content": ""}
    assert fake_llm.calls == 1


def test_bind_accepts_a_reference_to_an_empty_prior_output(fake_llm, sample_card):
    """A prior output that happens to be empty is still a resolved value.
    Two notes created with only a title both have empty content; the second
    instance referencing the first is correct, not a missing input."""
    card = replace(
        sample_card, inputs=["title (required)", "content (required)"]
    )
    fake_llm.responses = [
        {"bindings": {"title": "Keep this one", "content": "$create_note.content"}}
    ]

    out = ParamBinder(fake_llm).bind(
        card,
        Goal("Create a second note titled Keep this one"),
        "list",
        {"create_note.title": "Temporary memo", "create_note.content": ""},
    )

    assert out == {"title": "Keep this one", "content": ""}
    assert fake_llm.calls == 1


def test_bind_optional_input_may_be_missing(fake_llm, sample_card):
    fake_llm.responses = [{"bindings": {"title": "Trip"}}]
    assert ParamBinder(fake_llm).bind(
        sample_card, Goal("create a note"), "state", {}
    ) == {"title": "Trip"}


def test_bind_uses_the_label_the_build_showed_when_the_goal_names_none(
    fake_llm,
):
    """A control's label is the build's wording, not something a goal names.

    The delete card names its menu item by placeholder.  The goal says
    "delete Temporary memo" -- it never says what the build calls that menu
    row -- so the model guessed "Delete" where the build says "Delete
    note", and the plan tapped a row that does not exist.  The card records
    the label the trace saw; the binder uses it when the goal supplies no
    value.
    """
    card = replace(
        _delete_card(),
        inputs=[
            "delete_note_label (optional): label of the delete item; "
            "observed: 'Delete note'"
        ],
    )
    fake_llm.responses = [{"bindings": {"delete_note_label": ""}}]

    out = ParamBinder(fake_llm).bind(
        card, Goal("delete Temporary memo"), "detail screen", {}
    )

    assert out == {"delete_note_label": "Delete note"}


def test_bind_keeps_a_value_the_goal_does_name(fake_llm):
    """The observed label is a fallback, not an override."""
    card = replace(
        _delete_card(),
        inputs=[
            "delete_note_label (optional): label of the delete item; "
            "observed: 'Delete note'"
        ],
    )
    fake_llm.responses = [{"bindings": {"delete_note_label": "Archive"}}]

    out = ParamBinder(fake_llm).bind(
        card, Goal("archive the note instead"), "detail screen", {}
    )

    assert out == {"delete_note_label": "Archive"}


def _delete_card():
    from specfcg.models import FunctionCard

    return FunctionCard(
        name="delete_opened_note",
        intent="Delete the open note",
        inputs=["delete_note_label (required): label of the delete item"],
        preconditions="a note is open",
        postconditions="the note is gone",
        effects_outputs="note deleted",
    )

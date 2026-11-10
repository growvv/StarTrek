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


def test_bind_optional_input_may_be_missing(fake_llm, sample_card):
    fake_llm.responses = [{"bindings": {"title": "Trip"}}]
    assert ParamBinder(fake_llm).bind(
        sample_card, Goal("create a note"), "state", {}
    ) == {"title": "Trip"}

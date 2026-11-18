from __future__ import annotations

from specfcg.benchmark.coverage_eval import FunctionSpec
from specfcg.benchmark.selfopt import (
    growth,
    make_round,
    next_target,
    new_card_names,
)
from specfcg.models import FunctionCard, Graph


def _card(name: str) -> FunctionCard:
    return FunctionCard(
        name=name,
        intent=f"intent {name}",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",

        success_count=1,
        attempt_count=1,
    )


def test_next_target_returns_first_uncovered_function():
    functions = [
        FunctionSpec(id="a", label="A"),
        FunctionSpec(id="b", label="B"),
    ]
    assert next_target(functions, {"a"}).id == "b"
    assert next_target(functions, {"a", "b"}) is None


def test_new_card_names_reports_only_added_cards():
    before = Graph(cards={"a": _card("a")})
    after = Graph(cards={"a": _card("a"), "b": _card("b")})
    assert new_card_names(before, after) == ["b"]
    assert new_card_names(after, after) == []


def test_make_round_records_card_and_coverage_gain():
    functions = [
        FunctionSpec(id="a", label="A", cards=["a"]),
        FunctionSpec(id="b", label="B", cards=["b"]),
    ]
    before = Graph(cards={"a": _card("a")})
    after = Graph(cards={"a": _card("a"), "b": _card("b")})
    row = make_round(
        index=1,
        target=functions[1],
        goal="do b",
        before=before,
        after=after,
        functions=functions,
        reason="completed capability b",
    )
    assert row.cards_before == 1
    assert row.cards_after == 2
    assert row.covered_before == 1
    assert row.covered_after == 2
    assert row.added_cards == ["b"]
    assert row.completed is True
    assert row.reason == "completed capability b"


def test_make_round_marks_no_gain_as_not_completed():
    functions = [FunctionSpec(id="b", label="B", cards=["b"])]
    graph = Graph(cards={"a": _card("a")})
    row = make_round(
        index=1,
        target=functions[0],
        goal="do b",
        before=graph,
        after=graph,
        functions=functions,
    )
    assert row.added_cards == []
    assert row.covered_after == row.covered_before == 0
    assert row.completed is False


def test_growth_summarises_the_curve():
    functions = [
        FunctionSpec(id="a", label="A", cards=["a"]),
        FunctionSpec(id="b", label="B", cards=["b"]),
    ]
    start = Graph(cards={"a": _card("a")})
    end = Graph(cards={"a": _card("a"), "b": _card("b")})
    rows = [
        make_round(
            index=1,
            target=functions[1],
            goal="do b",
            before=start,
            after=end,
            functions=functions,
        )
    ]
    summary = growth(rows, start, end, functions)
    assert summary["rounds"] == 1
    assert summary["completed"] == 1
    assert summary["cards_added"] == 1
    assert summary["covered_start"] == 1
    assert summary["covered_end"] == 2
    assert summary["total"] == 2
    assert summary["curve"] == [1, 2]


def test_a_growing_graph_earns_the_same_target_one_more_attempt():
    """A round that added a card but missed its target is a prefix, not a
    dead end: the new card and the screen the probe left behind are often
    exactly what the next step needs.  Re-explore the same function while
    the graph is growing; move on when it stops."""
    from specfcg.benchmark.selfopt import next_attempt

    functions = [
        FunctionSpec(id="a", label="A"),
        FunctionSpec(id="b", label="B"),
        FunctionSpec(id="c", label="C"),
    ]
    target_a = functions[0]

    assert (
        next_attempt(
            functions, {"b"}, {"a": 1}, last_target=target_a, last_grew=True
        )
        is target_a
    )
    assert (
        next_attempt(
            functions, {"b"}, {"a": 1}, last_target=target_a, last_grew=False
        ).id
        == "c"
    )


def test_attempt_budget_bounds_the_retry():
    from specfcg.benchmark.selfopt import MAX_ATTEMPTS, next_attempt

    functions = [
        FunctionSpec(id="a", label="A"),
        FunctionSpec(id="b", label="B"),
    ]
    target_a = functions[0]

    chosen = next_attempt(
        functions,
        {"b"},
        {"a": MAX_ATTEMPTS},
        last_target=target_a,
        last_grew=True,
    )
    assert chosen is None  # budget spent and nothing else is uncovered

    functions.append(FunctionSpec(id="c", label="C"))
    chosen = next_attempt(
        functions,
        {"b"},
        {"a": MAX_ATTEMPTS},
        last_target=target_a,
        last_grew=True,
    )
    assert chosen.id == "c"


def test_a_covered_target_is_not_retried():
    from specfcg.benchmark.selfopt import next_attempt

    functions = [
        FunctionSpec(id="a", label="A"),
        FunctionSpec(id="b", label="B"),
    ]
    chosen = next_attempt(
        functions,
        {"a"},
        {"a": 1},
        last_target=functions[0],
        last_grew=True,
    )
    assert chosen.id == "b"


def test_next_target_skips_unreachable_functions():
    functions = [
        FunctionSpec(id="a", label="A"),
        FunctionSpec(id="ghost", label="Ghost", reachable=False),
        FunctionSpec(id="b", label="B"),
    ]

    assert next_target(functions, {"a"}).id == "b"
    assert next_target(functions, {"a", "b"}) is None


def test_a_round_only_completes_when_the_target_function_is_covered():
    """A card for something adjacent is not the target function.

    A round aimed at create_checklist that mines expand_note_creation_menu
    adds a card but leaves the target uncovered, and the curve must say so
    instead of counting it as a gain.
    """
    functions = [
        FunctionSpec(
            id="create_checklist", label="Create a checklist note",
            cards=["create_checklist"],
        ),
    ]
    before = Graph(cards={})
    after = Graph(cards={"expand_note_creation_menu": _card("expand_note_creation_menu")})

    row = make_round(
        index=1,
        target=functions[0],
        goal="create a checklist note",
        before=before,
        after=after,
        functions=functions,
        reason="completed capability expand_note_creation_menu",
    )

    assert row.added_cards == ["expand_note_creation_menu"]
    assert row.completed is False
    assert row.covered_after == 0


def test_next_target_skips_functions_already_attempted():
    """A round that fails must not be retried forever on the same function.

    next_target takes the covered set, so a caller can pass the functions it
    has already tried and walk on to the rest of the inventory.
    """
    functions = [
        FunctionSpec(id="a", label="A"),
        FunctionSpec(id="b", label="B"),
        FunctionSpec(id="c", label="C"),
    ]
    assert next_target(functions, {"a", "b"}).id == "c"


def test_growth_total_counts_the_functions_the_curve_counts():
    """The denominator must be the set the numerator was measured over.

    ``covered_before``/``covered_after`` come from ``graph_coverage``,
    which counts only reachable functions -- an entry the build cannot
    reach is reported separately, not as a gap.  Passing ``len(inventory)``
    as the total mixes the two: activitydiary showed 5→7 of 15 reachable
    functions against a total of 17, so the dimension understated the gain
    by the two entries no graph could ever cover.
    """
    functions = [
        FunctionSpec(id="a", label="A", cards=["a"]),
        FunctionSpec(id="b", label="B", cards=["b"]),
        FunctionSpec(id="x", label="X", reachable=False),
    ]
    start = Graph(cards={"a": _card("a")})
    end = Graph(cards={"a": _card("a"), "b": _card("b")})
    rows = [
        make_round(
            index=1,
            target=functions[1],
            goal="do b",
            before=start,
            after=end,
            functions=functions,
        )
    ]

    summary = growth(rows, start, end, functions)

    assert summary["total"] == 2
    assert summary["covered_start"] == 1
    assert summary["covered_end"] == 2

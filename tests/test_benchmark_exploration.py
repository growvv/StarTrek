from __future__ import annotations

from specfcg.benchmark.coverage_eval import FunctionSpec
from specfcg.benchmark.exploration import (
    build_probe,
    calibration,
    completion_goal,
    evidence_hit,
    predicted_route,
    uncovered,
)
from specfcg.models import Edge, FunctionCard, Graph


def _card(name: str, success: int = 1, attempts: int = 1) -> FunctionCard:
    return FunctionCard(
        name=name,
        intent=name,
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[],
        success_count=success,
        attempt_count=attempts,
    )


def test_uncovered_returns_functions_without_a_covered_id():
    functions = [
        FunctionSpec(id="a", label="A"),
        FunctionSpec(id="b", label="B"),
    ]
    assert [f.id for f in uncovered(functions, {"a"})] == ["b"]


def test_completion_goal_is_a_sentence():
    assert completion_goal(
        FunctionSpec(id="x", label="Archive a note")
    ) == "In the app, archive a note and leave the result visible on screen."


def test_predicted_route_uses_an_incoming_edge():
    graph = Graph(
        cards={"create_note": _card("create_note"), "archive_note": _card("archive_note")},
        edges=[Edge("create_note", "archive_note", "enables")],
    )
    function = FunctionSpec(id="archive", label="Archive", cards=["archive_note"])
    assert predicted_route(graph, function) == ["create_note", "archive_note"]


def test_predicted_route_without_edges_is_the_card_alone():
    graph = Graph(cards={"open_settings": _card("open_settings")})
    function = FunctionSpec(id="settings", label="Settings", cards=["open_settings"])
    assert predicted_route(graph, function) == ["open_settings"]


def test_predicted_route_of_a_missing_card_uses_the_graph_it_has():
    graph = Graph(cards={"create_note": _card("create_note")})
    function = FunctionSpec(id="merge", label="Merge", cards=["merge_notes"])
    assert predicted_route(graph, function) == ["create_note"]


def test_build_probe_carries_confidence_and_target():
    graph = Graph(
        cards={"create_note": _card("create_note", 8, 10), "archive_note": _card("archive_note")},
        edges=[Edge("create_note", "archive_note", "enables")],
    )
    function = FunctionSpec(
        id="archive", label="Archive a note", cards=["archive_note"]
    )
    probe = build_probe(graph, function)
    assert probe.target_card == "archive_note"
    assert probe.predicted_path == ["create_note", "archive_note"]
    # min(a=(8+1)/12, b=(1+1)/3) * 0.9 for the extra card
    assert round(probe.predicted_confidence, 3) == 0.6
    assert probe.reached is False


def test_evidence_hit_matches_any_ui_evidence():
    function = FunctionSpec(
        id="a", label="A", ui_evidence=["归档", "Archive"]
    )
    assert evidence_hit(function, "菜单\n归档") is True
    assert evidence_hit(function, "Archive this note") is True
    assert evidence_hit(function, "笔记列表") is False


def test_calibration_reports_predicted_actual_and_gap():
    probes = [
        build_probe(
            Graph(cards={"a": _card("a", 1, 2)}),
            FunctionSpec(id="a", label="A", cards=["a"]),
        ),
        build_probe(
            Graph(cards={"b": _card("b", 1, 1)}),
            FunctionSpec(id="b", label="B", cards=["b"]),
        ),
    ]
    probes[0].reached = True
    probes[1].reached = False
    result = calibration(probes)
    assert result["probes"] == 2
    # (1+1)/(2+2) = 0.5 and (1+1)/(1+2) = 0.667, both covered paths
    assert result["predicted"] == round((0.5 + 2 / 3) / 2, 3)
    assert result["actual"] == 0.5
    assert result["gap"] == round(result["predicted"] - result["actual"], 3)


def test_calibration_of_no_probes_is_zero():
    assert calibration([]) == {
        "probes": 0,
        "predicted": 0.0,
        "actual": 0.0,
        "gap": 0.0,
    }


def test_predicted_route_of_an_uncovered_function_starts_at_its_gateway():
    """An uncovered function has no card, so the route must be predicted from
    the cards that already exist: the graph's entry points into that area of
    the app.  Otherwise every probe predicts 0.0 and the calibration metric
    compares a constant against the outcome.
    """
    graph = Graph(
        cards={
            "open_note": _card("open_note", 4, 4),
            "open_navigation_drawer": _card("open_navigation_drawer", 2, 2),
        },
        edges=[
            Edge("open_note", "open_note", "sequence"),
            Edge("open_navigation_drawer", "open_settings", "enables"),
        ],
    )
    function = FunctionSpec(
        id="open_settings",
        label="Open app settings",
        cards=["open_settings"],
        ui_evidence=["设置"],
    )

    probe = build_probe(graph, function)

    assert probe.target_card == "open_navigation_drawer"
    assert probe.predicted_path == ["open_navigation_drawer"]
    assert probe.predicted_confidence > 0.0


def test_predicted_route_falls_back_to_the_best_covered_card():
    """With no edge naming the missing card, the most reliable card is the
    closest thing the graph knows about that part of the app."""
    graph = Graph(
        cards={
            "open_navigation_drawer": _card("open_navigation_drawer", 1, 4),
            "open_note": _card("open_note", 3, 4),
        }
    )
    function = FunctionSpec(id="open_settings", label="Settings")

    probe = build_probe(graph, function)

    assert probe.predicted_path == ["open_note"]
    # (3+1)/(4+2) smoothed rate x the 0.5 unexecuted-step prior
    assert round(probe.predicted_confidence, 3) == 0.333


def test_predicted_route_of_an_empty_graph_is_empty():
    function = FunctionSpec(id="open_settings", label="Settings")
    probe = build_probe(Graph(cards={}), function)
    assert probe.predicted_path == []
    assert probe.predicted_confidence == 0.0


def test_probe_confidence_discounts_the_unmodelled_target_step():
    """The gateway card is covered, the function's own step is not.

    Predicting the covered card's success rate alone would say 1.00 for
    every uncovered function, so the probe would never express uncertainty
    about the part the graph does not know.
    """
    graph = Graph(cards={"open_navigation_drawer": _card("open_navigation_drawer", 4, 4)})
    function = FunctionSpec(id="open_settings", label="Open settings")

    probe = build_probe(graph, function)

    # (4+1)/(4+2) smoothed rate x the 0.5 unexecuted-step prior
    assert round(probe.predicted_confidence, 3) == 0.417
    assert probe.target_card == "open_navigation_drawer"


def test_probe_confidence_keeps_a_covered_paths_estimate():
    graph = Graph(
        cards={"create_note": _card("create_note", 8, 10), "archive_note": _card("archive_note")},
        edges=[Edge("create_note", "archive_note", "enables")],
    )
    function = FunctionSpec(id="archive", label="Archive", cards=["archive_note"])

    probe = build_probe(graph, function)

    # min(a=(8+1)/12, b=(1+1)/3) * 0.9 for the extra card
    assert round(probe.predicted_confidence, 3) == 0.6


def test_uncovered_skips_functions_the_build_cannot_reach():
    """A probe on an unreachable control can only ever fail.

    The inventory marks such entries reachable: false with a note; spending
    a probe on them reports a miss the graph was never able to fix.
    """
    functions = [
        FunctionSpec(id="a", label="A"),
        FunctionSpec(id="attach", label="Attach", reachable=False),
    ]
    assert [f.id for f in uncovered(functions, set())] == ["a"]


def test_one_observation_is_not_certainty():
    """A card seen once is evidence, not proof.

    Every card mined from one trace is 1/1, and ``success/attempt`` reads
    that as a 1.00 success rate.  The result is that every probe predicts
    the same confidence -- a constant cannot be calibrated against
    anything, so the calibration dimension measured nothing.  Laplace
    smoothing keeps one observation strong evidence without calling it
    certainty.
    """
    graph = Graph(cards={"open_note": _card("open_note", 1, 1)})
    function = FunctionSpec(
        id="archive", label="Archive", cards=["archive_note"]
    )

    probe = build_probe(graph, function)

    # (1+1)/(1+2) for the card, x the 0.5 unexecuted-step prior
    assert round(probe.predicted_confidence, 3) == 0.333


def test_a_reliable_card_still_earns_a_higher_estimate():
    """Smoothing must not flatten the graph's evidence into one number.

    A card executed successfully four times is likelier to be executable
    than one seen once, and the estimate has to say so -- otherwise the
    calibration metric is measuring a constant again.
    """
    once = build_probe(
        Graph(cards={"open_note": _card("open_note", 1, 1)}),
        FunctionSpec(id="a", label="A", cards=["missing"]),
    )
    often = build_probe(
        Graph(cards={"open_note": _card("open_note", 4, 4)}),
        FunctionSpec(id="a", label="A", cards=["missing"]),
    )

    assert often.predicted_confidence > once.predicted_confidence


def test_probe_confidence_prices_the_unmodelled_step_with_the_unexecuted_prior():
    """The step the graph cannot model is priced like any unexecuted card.

    ``0.45`` was a number with no meaning behind it.  The graph already has
    a prior for a card it has never executed -- an even chance -- and the
    final, unmodelled step of a probe is exactly that: a step the graph has
    never executed.  Pricing it the same way keeps one number for one idea.
    """
    graph = Graph(cards={"open_note": _card("open_note", 4, 4)})
    function = FunctionSpec(
        id="archive", label="Archive", cards=["archive_note"]
    )

    probe = build_probe(graph, function)

    # (4+1)/(4+2) smoothed card rate x the 0.5 unexecuted-step prior
    assert round(probe.predicted_confidence, 3) == 0.417

"""Task-guided exploration of an incomplete graph.

The idea under test: when a function is not yet covered, propose a task whose
route (predicted from the graph) should reach the card that implements it,
estimate how likely that route is to be executable, then run it and record
whether the node was actually reached.  The comparison between the predicted
probability and the empirical hit rate is the calibration metric.
"""

from __future__ import annotations

from dataclasses import dataclass

from specfcg.scoring.coverage_eval import (
    UNEXECUTED_PRIOR,
    FunctionSpec,
    _tokens,
    path_confidence,
)
from specfcg.models import Graph


@dataclass
class CompletionProbe:
    function_id: str
    label: str
    goal: str
    target_card: str
    predicted_path: list[str]
    predicted_confidence: float
    reached: bool = False
    observed_evidence: str = ""


def uncovered(
    functions: list[FunctionSpec],
    covered_ids: set[str],
) -> list[FunctionSpec]:
    """Functions with no card that a probe could actually reach.

    An entry marked ``reachable: false`` is declared by the source but
    cannot be reached on this device, so probing it can only report a miss
    the graph was never able to fix.
    """
    return [
        function
        for function in functions
        if function.id not in covered_ids and function.reachable
    ]


def completion_goal(function: FunctionSpec) -> str:
    """A natural-language task that should exercise the uncovered function."""
    label = (function.label or function.id).strip().rstrip(".")
    return (
        f"In the app, {label[0].lower() + label[1:]} "
        "and leave the result visible on screen."
    )


def predicted_route(graph: Graph, function: FunctionSpec) -> list[str]:
    """The graph path a planner would take toward this function.

    A covered function is reached through the card that implements it (and
    the card that enables it).  An uncovered function has no card, so the
    route is predicted from the cards that do exist: the card whose edge
    names the missing one, else the most reliable card the graph knows.
    """
    for name in function.cards:
        if name in graph.cards:
            incoming = graph.incoming(name)
            if incoming:
                parents = sorted({edge.from_card for edge in incoming})
                return [parents[0], name]
            return [name]
    return _gateway(graph, function)


def _gateway(graph: Graph, function: FunctionSpec) -> list[str]:
    """The best existing card to stand in for an uncovered function.

    The card whose edge names the missing one wins; failing that, the card
    that shares the most vocabulary with the function (``open_settings`` and
    ``open_navigation_drawer`` both say open), and among equals the most
    reliable one.
    """
    wanted = set(function.cards)
    gateways = {
        edge.from_card
        for edge in graph.edges
        if edge.to_card in wanted and edge.from_card in graph.cards
    }
    pool = sorted(gateways) or sorted(graph.cards)
    if not pool:
        return []
    vocabulary = _tokens(function.id)
    for name in function.cards:
        vocabulary |= _tokens(name)
    return [
        max(
            pool,
            key=lambda name: (
                len(_tokens(name) & vocabulary),
                path_confidence(graph, [name]),
            ),
        )
    ]


def build_probe(graph: Graph, function: FunctionSpec) -> CompletionProbe:
    """A task, the route the graph predicts, and how likely that route is.

    When the function has a card the route is the card's own path and the
    estimate is that path's confidence.  When it does not, the route stops at
    a gateway card and the last step -- the function itself -- is not in the
    graph.  That step is a step the graph has never executed, so it is
    priced the way the graph prices any unexecuted step.
    """
    path = predicted_route(graph, function)
    # The route only models the function itself when it ends at the
    # function's own card; ending at a gateway means the last step is a
    # hypothesis, not something the graph has executed.
    covered = bool(path) and path[-1] in function.cards
    confidence = path_confidence(graph, path) if path else 0.0
    if path and not covered:
        confidence *= UNEXECUTED_PRIOR
    return CompletionProbe(
        function_id=function.id,
        label=function.label or function.id,
        goal=completion_goal(function),
        target_card=path[-1] if path else "",
        predicted_path=path,
        predicted_confidence=confidence,
    )


def evidence_hit(function: FunctionSpec, observed_text: str) -> bool:
    haystack = (observed_text or "").casefold()
    return any(
        evidence.casefold() in haystack
        for evidence in function.ui_evidence
    )


def brier(probes: list[CompletionProbe]) -> float:
    """Mean squared error of each prediction against what actually happened.

    A proper score: it is minimised by the true probability, so a constant
    that happens to match the base rate still pays for being wrong about
    every individual probe.  The bias score (``1 - |predicted - actual|``)
    does not have that property -- any constant near the base rate scores
    well -- which is why the spread is reported beside it.
    """
    if not probes:
        return 0.0
    total = sum(
        (probe.predicted_confidence - (1.0 if probe.reached else 0.0)) ** 2
        for probe in probes
    )
    return round(total / len(probes), 4)


def calibration(probes: list[CompletionProbe]) -> dict[str, float]:
    """Predicted vs empirical coverage rate over the probes.

    ``distinct_predictions`` is the number of different values the estimator
    produced.  One means the estimator is constant, and a constant cannot
    discriminate between probes however good its bias looks.
    """
    if not probes:
        return {
            "probes": 0,
            "predicted": 0.0,
            "actual": 0.0,
            "gap": 0.0,
            "brier": 0.0,
            "distinct_predictions": 0,
        }
    predicted = sum(probe.predicted_confidence for probe in probes) / len(
        probes
    )
    actual = sum(1 for probe in probes if probe.reached) / len(probes)
    return {
        "probes": len(probes),
        "predicted": round(predicted, 3),
        "actual": round(actual, 3),
        "gap": round(predicted - actual, 3),
        "brier": brier(probes),
        "distinct_predictions": len(
            {round(probe.predicted_confidence, 6) for probe in probes}
        ),
    }

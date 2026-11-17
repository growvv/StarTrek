"""Iterative self-improvement of a function graph, measured round by round.

The method under test: a graph that is incomplete can be grown by proposing
the next uncovered function as a task, letting the existing capability
completion path (plan -> execute -> mine the probe trace) add the missing
card, and then re-measuring coverage.  This module contains only the
bookkeeping: which function to attempt next, what a round changed, and the
coverage curve.  Planning, probing, and card mining stay in the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from specfcg.benchmark.coverage_eval import FunctionSpec, graph_coverage
from specfcg.models import Graph


def next_target(
    functions: list[FunctionSpec], covered: set[str]
) -> FunctionSpec | None:
    """The next function to attempt: the first reachable uncovered entry.

    An entry marked ``reachable: false`` is declared by the source but cannot
    be reached on the device, so no amount of planning will cover it; trying
    it would spend a round and report a false failure.
    """
    for function in functions:
        if function.id not in covered and function.reachable:
            return function
    return None


MAX_ATTEMPTS = 2


def next_attempt(
    functions: list[FunctionSpec],
    covered: set[str],
    attempts: dict[str, int],
    *,
    last_target: FunctionSpec | None,
    last_grew: bool,
) -> FunctionSpec | None:
    """The target for the next round.

    A round that added a card but missed its target is a prefix, not a dead
    end: the new card, and the screen the probe left behind, are often
    exactly what the next step needs.  So the same function is attempted
    again while the graph is still growing, bounded by ``MAX_ATTEMPTS``; a
    round that adds nothing moves the loop on.
    """
    if (
        last_target is not None
        and last_target.id not in covered
        and last_grew
        and attempts.get(last_target.id, 0) < MAX_ATTEMPTS
    ):
        return last_target
    return next_target(functions, covered | set(attempts))


def new_card_names(before: Graph, after: Graph) -> list[str]:
    """Cards that exist in ``after`` but not in ``before``, in name order."""
    return sorted(set(after.cards) - set(before.cards))


@dataclass
class RoundRecord:
    index: int
    function: str
    label: str
    goal: str
    cards_before: int
    cards_after: int
    covered_before: int
    covered_after: int
    added_cards: list[str] = field(default_factory=list)
    completed: bool = False
    reason: str = ""


def make_round(
    *,
    index: int,
    target: FunctionSpec,
    goal: str,
    before: Graph,
    after: Graph,
    functions: list[FunctionSpec],
    reason: str = "",
) -> RoundRecord:
    covered_before = graph_coverage(functions, before)
    covered_after = graph_coverage(functions, after)
    added = new_card_names(before, after)
    # A round succeeds when the function it aimed at is now covered.  A card
    # for something adjacent (the menu that opens the checklist sheet) is
    # progress, but it is not the capability the round asked for.
    completed = target.id in covered_after.hits
    return RoundRecord(
        index=index,
        function=target.id,
        label=target.label or target.id,
        goal=goal,
        cards_before=len(before.cards),
        cards_after=len(after.cards),
        covered_before=covered_before.covered,
        covered_after=covered_after.covered,
        added_cards=added,
        completed=completed,
        reason=reason,
    )


def growth(
    rounds: list[RoundRecord],
    start: Graph,
    end: Graph,
    functions: list[FunctionSpec],
) -> dict:
    """Summary of one self-optimization run: gains and the coverage curve.

    The total is the count of reachable functions, not the length of the
    inventory: ``covered_*`` come from ``graph_coverage``, which reports an
    unreachable entry separately instead of counting it as a gap.  Taking
    the two from different sets would make the dimension compare a
    numerator over reachable functions against a denominator over all of
    them, and understate every gain.
    """
    total = len([function for function in functions if function.reachable])
    return {
        "rounds": len(rounds),
        "completed": sum(1 for row in rounds if row.completed),
        "cards_added": len(new_card_names(start, end)),
        "cards_start": len(start.cards),
        "cards_end": len(end.cards),
        "covered_start": rounds[0].covered_before if rounds else 0,
        "covered_end": rounds[-1].covered_after if rounds else 0,
        "total": total,
        "curve": ([rounds[0].covered_before] if rounds else [])
        + [row.covered_after for row in rounds],
    }

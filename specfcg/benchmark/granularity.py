"""Do the graph's cards name distinct functions?

A card is a node in the Function Contract Graph, and its value rests on being
the *only* way the graph describes that function.  Two cards that send the
device the same actions on the same controls are one node written twice: the
search pays for both, coverage credits neither more than once, and the graph
reports an inventory richer than the app it describes.

The comparison is behavioural, not lexical.  Card names are free text the
miner invents per trace, so name similarity flags ``show_file_properties``
against ``show_hidden_files`` -- two different functions -- while missing
``open_note`` and ``open_note_from_list``, which are the same tap on the same
control.  The surface here is the one the compiler itself would execute.

There is no similarity threshold.  Two surfaces are either the same set of
action/control pairs or they are not; a threshold would only be needed to
decide how close is close enough to *merge*, which this module does not do.
It measures, so that a graph that has grown duplicates can say so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from specfcg.models import FunctionCard
from specfcg.planner.compiler import StepCompiler

Action = tuple[str, str]


@dataclass(frozen=True)
class Surface:
    """What a card does to the screen: an action on an identified control."""

    actions: frozenset[Action]


_PARAMETER_RE = re.compile(r"\{[^{}]+\}")


def _control(target: str) -> str:
    """The control a compiled target addresses, without the value bound to it.

    ``resourceId=...:id/note_title|text={note_title}`` names the control and a
    placeholder for what it will read: the caller's input, not the card's
    behaviour, so the same card called with another note is the same node.

    A *literal* label is different.  Archive and pin are two menu rows that
    share one generic resource id; ``text=归档`` and ``text=置顶笔记`` are the
    only thing telling them apart, and the device finds the row by that label.
    Stripping it would merge two different functions into one node.
    """
    locator, _, value = target.partition("|")
    if value and not _PARAMETER_RE.search(value):
        return target.strip()
    return locator.strip()


def card_surface(card: FunctionCard) -> Surface | None:
    """The card's behaviour, or None when it needs the model to resolve.

    A card whose steps the compiler cannot parse without asking the model has
    no behaviour surface that can be compared deterministically.  Returning
    None keeps it out of the comparison instead of guessing a surface for it.
    """
    steps = StepCompiler.explicit_steps(card)
    if not steps:
        return None
    return Surface(
        frozenset((step.action, _control(step.target)) for step in steps)
    )


@dataclass
class Granularity:
    cards: int
    measured: int
    distinct: int
    duplicate_groups: list[list[str]] = field(default_factory=list)

    @property
    def score(self) -> float | None:
        """Distinct behaviours per measured card.

        1.0 means every card the compiler could resolve is its own node.  It
        is None when no card resolved: a comparison that was never made has
        no score, and calling it 1.0 would report a graph of any quality as
        perfectly granular.
        """
        if not self.measured:
            return None
        return self.distinct / self.measured

    def as_record(self) -> dict:
        return {
            "cards": self.cards,
            "measured": self.measured,
            "distinct": self.distinct,
            "score": self.score,
            "duplicate_groups": self.duplicate_groups,
        }


def granularity(cards: dict[str, FunctionCard]) -> Granularity:
    """Group the cards by behaviour and report how many distinct nodes there are."""
    groups: dict[frozenset[Action], list[str]] = {}
    measured = 0
    for name in sorted(cards):
        surface = card_surface(cards[name])
        if surface is None:
            continue
        measured += 1
        groups.setdefault(surface.actions, []).append(name)
    duplicates = sorted(
        names for names in groups.values() if len(names) > 1
    )
    return Granularity(
        cards=len(cards),
        measured=measured,
        distinct=len(groups),
        duplicate_groups=duplicates,
    )

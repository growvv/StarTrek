"""Render a planned path as the task description a GUI agent is given.

The planner decides *which* functions to run, in what order, and with which
values.  The describer turns that into prose an agent can act on, and it is
deterministic: no model call, so the same plan always produces the same text.

It states the goal, then each subgoal's contract -- intent, the values it
needs, what must hold before and after, and how reliable the card has been.
It names no UI action.  Deciding *how* to achieve a subgoal is the agent's
job; a description that also dictated the taps would be the old replay with a
different name.
"""

from __future__ import annotations

import re
from typing import Iterable

from specfcg.models import FunctionCard

UNBOUND = "<unbound: not named in the goal or earlier outputs>"


def _input_names(card: FunctionCard) -> list[str]:
    """The parameter names a card declares, in declaration order."""
    names: list[str] = []
    for declaration in card.inputs:
        parts = declaration.split()
        if parts:
            names.append(parts[0])
    return names


def _origin(name: str, earlier: list[FunctionCard]) -> str:
    """Which earlier subgoal produced this value, if any.

    A value flows forward when an earlier card's postconditions or effects
    name it: that card is what put the note, the file, the folder in place
    for this one to consume.  Naming the source lets the agent look for the
    value where it already exists instead of inventing it.
    """
    pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
    for index, card in enumerate(earlier, start=1):
        produced = f"{card.postconditions} {card.effects_outputs}"
        if pattern.search(produced):
            return f" (from subgoal {index})"
    return ""


class TaskDescriber:
    """Render a path of (card, bindings) pairs as one task description."""

    def describe(
        self,
        goal: str,
        subgoals: Iterable[tuple[FunctionCard, dict[str, str]]],
    ) -> str:
        steps = list(subgoals)
        lines = [f"Overall goal: {goal}", ""]
        if not steps:
            return "\n".join(lines).rstrip() + "\n"

        lines.append("Subgoals, in order:")
        earlier: list[FunctionCard] = []
        for index, (card, bindings) in enumerate(steps, start=1):
            lines.append(f"{index}. {card.name} — {card.intent}")
            pairs = []
            for name in _input_names(card):
                if name in bindings:
                    value = bindings[name]
                    pairs.append(f"{name} = {value}{_origin(name, earlier)}")
                else:
                    pairs.append(f"{name} = {UNBOUND}")
            lines.append(f"   Inputs: {'; '.join(pairs) if pairs else 'none'}")
            lines.append(f"   Preconditions: {card.preconditions}")
            lines.append(f"   Postconditions: {card.postconditions}")
            lines.append(
                f"   Reliability: {card.success_count}/{card.attempt_count} "
                "observed successes"
            )
            lines.append("")
            earlier.append(card)
        return "\n".join(lines).rstrip() + "\n"

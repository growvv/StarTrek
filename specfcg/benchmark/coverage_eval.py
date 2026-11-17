"""Coverage scoring for function graphs and observed UI traces.

Two independent estimates are supported:

* ``graph_coverage``: how many source-inventoried functions have a card in
  the graph (graph completeness against the source-derived ground truth).
* ``observed_coverage``: how many functions were seen during random
  traversal or a targeted run (does the graph/app reach the function at all).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from specfcg.models import FunctionCard, Graph


@dataclass
class FunctionSpec:
    id: str
    label: str = ""
    source: str = ""
    cards: list[str] = field(default_factory=list)
    ui_evidence: list[str] = field(default_factory=list)
    reachable: bool = True
    note: str = ""


@dataclass
class CoverageReport:
    total: int
    covered: int
    score: float
    missing: list[str] = field(default_factory=list)
    hits: dict[str, str] = field(default_factory=dict)
    unreachable: list[str] = field(default_factory=list)
    hint_dependence: float = 0.0

    def as_record(self) -> dict[str, Any]:
        """The shape the experiments write, so the scorecard reads one form."""
        return {
            "functions": self.total,
            "covered": self.covered,
            "score": round(self.score, 3),
            "missing": list(self.missing),
            "unreachable": list(self.unreachable),
            "hits": dict(self.hits),
            "hint_dependence": round(self.hint_dependence, 3),
        }


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value if str(item).strip()]


def load_inventory(path: Path) -> list[FunctionSpec]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: root must be a mapping")
    items = raw.get("functions")
    if not isinstance(items, list):
        raise ValueError(f"{path}: 'functions' must be a list")
    functions: list[FunctionSpec] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"{path}: function entries must be mappings")
        function_id = str(item.get("id") or "").strip()
        if not function_id:
            raise ValueError(f"{path}: function needs an id")
        functions.append(
            FunctionSpec(
                id=function_id,
                label=str(item.get("label") or "").strip(),
                source=str(item.get("source") or "").strip(),
                cards=_list(item.get("cards")),
                ui_evidence=_list(item.get("ui_evidence")),
                reachable=item.get("reachable", True) is not False,
                note=str(item.get("note") or "").strip(),
            )
        )
    return functions


_SYNONYMS = {
    "add": "create",
    "new": "create",
    "insert": "create",
    "remove": "delete",
    "trash": "delete",
    "view": "open",
    "browse": "open",
    "go": "open",
    "jump": "open",
    "navigate": "open",
    "unarchive": "restore",
    "set": "assign",
}
# Inflections whose stem is not derivable by dropping a suffix: a mined card
# says "archived"/"opened" where the inventory says "archive"/"open".
_LEMMAS = {
    "archived": "archive",
    "opened": "open",
    "assigned": "assign",
    "created": "create",
    "deleted": "delete",
    "edited": "edit",
    "added": "create",
}
_VERBS = frozenset(
    {
        "open",
        "create",
        "delete",
        "edit",
        "show",
        "start",
        "stop",
        "share",
        "move",
        "copy",
        "sort",
        "search",
        "assign",
        "toggle",
        "restore",
    }
)


def _stem(token: str) -> str:
    if token in _LEMMAS:
        return _LEMMAS[token]
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        return token[:-1]
    return token


def _tokens(name: str) -> set[str]:
    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", name.casefold())
        if token
    }
    return {
        _SYNONYMS.get(stemmed, stemmed)
        for stemmed in (_stem(token) for token in tokens)
    }


def _is_compound(name: str) -> bool:
    """A card name joining two actions, e.g. create_and_assign_category."""
    return "and" in re.split(r"[^a-z0-9]+", name.casefold())


def _leading_verb(name: str) -> str | None:
    """The action a name starts with, e.g. delete for delete_opened_note."""
    first = re.split(r"[^a-z0-9]+", name.casefold())
    for token in first:
        if token:
            stemmed = _SYNONYMS.get(_stem(token), _stem(token))
            return stemmed if stemmed in _VERBS else None
    return None


def _candidates(
    function: FunctionSpec,
    card_names: set[str],
    other_tokens: set[str],
) -> list[tuple[int, int, str]]:
    """(rank, tie_penalty, card) matches for one function; lower is better.

    Mined card names are not predictable (``stop_current_activity`` for a
    function the inventory calls ``stop_activity``), so a token match is used
    as a fallback.  The function's tokens must be a subset of the card's, and
    an extra card token must not be a verb of its own -- so ``share_note``
    matches ``share_note_via_system_chooser`` while ``open_note`` never
    matches ``delete_opened_note``.  A compound name (``create_and_assign_
    category``) may carry an extra verb, because it really does two things.
    A single-token function only matches when that token has one owner, so
    ``open`` alone cannot claim every ``open_*`` card.

    The tie penalty counts extra tokens that name another inventory function
    (``checklist`` belongs to ``create_checklist``), so ``create_note`` takes
    ``create_text_note`` and leaves ``create_checklist_note`` to its owner.
    """
    out: list[tuple[int, int, str]] = []
    for candidate in (function.id,):
        wanted = _tokens(candidate)
        if not wanted:
            continue
        if len(wanted) == 1:
            token = next(iter(wanted))
            owners = [
                name
                for name in sorted(card_names)
                if token in _tokens(name)
            ]
            if len(owners) == 1:
                out.append((1, 0, owners[0]))
            continue
        for name in sorted(card_names):
            have = _tokens(name)
            if not have or not wanted <= have:
                continue
            extra = have - wanted
            if extra & _VERBS and not _is_compound(name):
                # A descriptive participle ("delete_opened_note") is fine as
                # long as the card still performs the function's action.
                if _leading_verb(name) != _leading_verb(candidate):
                    continue
            out.append(
                (1 + len(extra), len(extra & other_tokens), name)
            )
    return out


def _assign_cards(
    functions: list[FunctionSpec], card_names: set[str]
) -> dict[str, str]:
    """Match every function to at most one card, and each card to one function."""
    tokens_by_function = {
        function.id: _tokens(function.id).union(
            *(  # noqa: C419 -- explicit union over the card hints
                _tokens(name) for name in function.cards
            )
        )
        for function in functions
    }
    pairs: list[tuple[int, int, int, str]] = []
    for index, function in enumerate(functions):
        others: set[str] = set()
        for other_id, tokens in tokens_by_function.items():
            if other_id != function.id:
                others |= tokens
        for rank, penalty, name in _candidates(
            function, card_names, others
        ):
            pairs.append((rank, penalty, index, name))
    pairs.sort()
    assigned: dict[str, str] = {}
    used: set[str] = set()
    for _, _, index, name in pairs:
        function_id = functions[index].id
        if function_id in assigned or name in used:
            continue
        assigned[function_id] = name
        used.add(name)
    return assigned


def _reachable(functions: list[FunctionSpec]) -> list[FunctionSpec]:
    return [function for function in functions if function.reachable]


def graph_coverage(
    functions: list[FunctionSpec], graph: Graph
) -> CoverageReport:
    """Graph completeness over the functions this build can reach.

    An inventory entry marked ``reachable: false`` declares a function the
    source exposes but the installed build cannot reach (a control that opens
    nothing, a menu the build does not ship).  It is reported separately
    instead of being counted as a graph gap, so the score measures the graph.

    The ``cards`` hint is deliberately not scored.  It names the card that
    implemented each function in *one particular build* -- usually the graph
    the inventory was written alongside -- so matching on it measures whether
    two builds agreed on a name.  Rebuilding activitydiary from the same
    traces, without the inventory in sight, produced ``edit_note`` for
    ``edit_diary_entry`` and ``filter_diary_by_activity`` for
    ``filter_history``: two functions performed, two functions counted
    missing, because the names differed.  ``hint_dependence`` reports how
    many functions the hints would have added, so the leak is visible instead
    of silently inflating the score.
    """
    card_names = set(graph.cards)
    reachable = _reachable(functions)
    assigned = _assign_cards(reachable, card_names)
    missing = [
        function.id
        for function in reachable
        if function.id not in assigned
    ]
    covered = len(reachable) - len(missing)
    total = len(reachable)
    hinted = sum(
        1
        for function in reachable
        if function.id not in assigned
        and any(name in card_names for name in function.cards)
    )
    return CoverageReport(
        total=total,
        covered=covered,
        score=covered / total if total else 0.0,
        missing=missing,
        hits=assigned,
        unreachable=[
            function.id for function in functions if not function.reachable
        ],
        hint_dependence=hinted / total if total else 0.0,
    )


def observed_coverage(
    functions: list[FunctionSpec], observed_text: str
) -> CoverageReport:
    haystack = (observed_text or "").casefold()
    covered = 0
    missing: list[str] = []
    hits: dict[str, str] = {}
    reachable = _reachable(functions)
    for function in reachable:
        matched = next(
            (
                evidence
                for evidence in function.ui_evidence
                if evidence.casefold() in haystack
            ),
            None,
        )
        if matched is None:
            missing.append(function.id)
        else:
            covered += 1
            hits[function.id] = matched
    total = len(reachable)
    return CoverageReport(
        total=total,
        covered=covered,
        score=covered / total if total else 0.0,
        missing=missing,
        hits=hits,
        unreachable=[
            function.id for function in functions if not function.reachable
        ],
    )


# A card the graph has never executed has an even chance of running: nothing
# observed argues either way, so neither certainty nor impossibility is
# justified.  One number for one idea, reused wherever the graph prices a
# step it has no evidence about.
UNEXECUTED_PRIOR = 0.5


def card_rate(card: FunctionCard) -> float:
    """The smoothed success rate of one card.

    ``success/attempt`` reads one successful run as a 1.00 rate, and almost
    every mined card is 1/1 -- so every path scores 1.0 and every probe
    predicts the same confidence.  A metric computed from a constant cannot
    measure anything.  Laplace smoothing keeps a single observation strong
    evidence without calling it certainty, and lets a card seen more often
    earn a rate closer to what it has actually shown.
    """
    attempts = card.attempt_count
    if not attempts:
        return UNEXECUTED_PRIOR
    return (card.success_count + 1) / (attempts + 2)


def path_confidence(graph: Graph, path: list[str]) -> float:
    """Estimated probability that a planned card path is executable.

    Cards contribute their smoothed success rate; every extra card beyond
    the first costs a reachability penalty, so a longer plan is never more
    confident than a shorter one.
    """
    if not path:
        return 0.0
    confidence = 1.0
    for name in path:
        card = graph.cards.get(name)
        if card is None:
            return 0.0
        confidence = min(confidence, card_rate(card))
    return confidence * (0.9 ** max(0, len(path) - 1))

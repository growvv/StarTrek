"""Segment traces into user-level functions and draft function cards."""

from __future__ import annotations

import logging
import re
from typing import Any

from specfcg.cards.parser import CardParseError, parse_card
from specfcg.cards.store import CardStore
from specfcg.llm.client import LLMClient, LLMParseError
from specfcg.models import CardPatch, FunctionCard, Step, Trace

logger = logging.getLogger(__name__)

_SEGMENT_SCHEMA = (
    '{"episodes": [{"start": 0, "end": 1, '
    '"name": "create_note", "intent": "create a note"}]}'
)
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_-]*)\}")
# The value a tap step carries can be trace data rather than a control
# label: `text=bench_new.txt` names the file this run happened to touch, and
# a card that keeps it can only ever repeat that one run.
_TARGET_VALUE_RE = re.compile(r"(?P<key>text|desc|description)=['\"]?(?P<value>[^|'\"\n]+)")
# Values that identify a screen region or a dialog action are part of the
# function, not of the run: a generic label a card may name literally.
_GENERIC_FIELD_WORDS = frozenset(
    {
        "id",
        "edit",
        "text",
        "input",
        "field",
        "view",
        "detail",
        "editor",
        "et",
        "dialog",
    }
)
_CARD_PROMPT = (
    "Write one reusable Markdown function card for this user-level episode. "
    "A card is a contract, not a script: describe what the function requires "
    "and what it leaves behind. Name no UI action, no tap, no key press, and "
    "no coordinate. "
    "Generalize trace-specific values: declare them as named inputs and "
    "refer to them as {name} in Intent, Preconditions, Postconditions and "
    "Effects/Outputs. Do not bake the single observed values into the card, "
    "and do not mention unrelated existing data from the trace. "
    "Use exactly these headings, each followed by a colon: **Intent**, "
    "**Inputs**, **Preconditions**, **Postconditions**, **Effects/Outputs**, "
    "**Evidence**. Do not write a Steps section. "
    "Write Inputs as one bullet per parameter in the form "
    "'- name (required|optional): description'. "
    "The first line must be '# <function_name>' using a reusable "
    "snake_case name. State preconditions as the screen or state the "
    "function needs, and postconditions as what is observably true after it "
    "succeeds; both must be reusable across runs, not a transcript of this "
    "one. Write Evidence exactly as "
    "'traces <trace_id>; <success>/<attempt> successes' with no prose. "
    "Use the trace evidence. Return only the Markdown card."
)


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _input_name(target: str, index: int) -> str:
    """A parameter name for an input field, from its resource id.

    ``...:id/detail_title`` -> ``title``; ``...:id/new_file_dialog__name``
    -> ``name``.  Generic layout words are dropped so the name reads like the
    user-facing value rather than the widget path.
    """
    entry = target.rsplit("/", 1)[-1] if ":id/" in target else ""
    if not entry:
        entry = target.split("=", 1)[-1]
    tokens = [
        token
        for token in re.split(r"[^A-Za-z0-9]+", entry.lower())
        if token and token not in _GENERIC_FIELD_WORDS
    ]
    return "_".join(tokens) or f"value_{index}"


def _ground_contract(
    card: FunctionCard, steps: list[Step], start_state: str = ""
) -> FunctionCard:
    """Make every value the contract names a declared input of the card.

    The contract is what the card promises: intent, preconditions,
    postconditions and effects.  Two kinds of value can hide in it.

    A ``{name}`` the model wrote is already a parameter; it only has to be
    declared, or the planner has nothing to bind.

    A literal the trace happened to carry is the harder case.  The model
    sometimes writes the run's own file or note name into the postcondition
    instead of a placeholder -- ``bench_new.txt now exists`` -- and a card
    like that promises one run's outcome and no other.  ``start_state`` is
    what tells data from vocabulary: a value the launch screen already showed
    as content is this run's data, so it becomes ``{item_label}``.

    The trace's steps are still read here, as evidence of what the screen
    showed.  That is what grounding is; it is not a replay.
    """
    declared = {item.split()[0] for item in card.inputs if item.split()}
    added: list[str] = []

    contract_fields = ("intent", "preconditions", "postconditions", "effects_outputs")

    # (1) placeholders in the contract must be declared inputs
    for field in contract_fields:
        for name in _PLACEHOLDER_RE.findall(getattr(card, field) or ""):
            if name in declared:
                continue
            declared.add(name)
            added.append(f"{name} (required): value named by the contract")

    # (2) a trace value written literally into the contract is data
    for field in contract_fields:
        text = getattr(card, field) or ""
        for step in steps:
            baked = _contract_trace_value(step, text, start_state)
            if baked is None:
                continue
            name = "item_label"
            suffix = 2
            while name in declared:
                name = f"item_label_{suffix}"
                suffix += 1
            declared.add(name)
            added.append(
                f"{name} (required): visible label of the item this function acts on"
            )
            text = text.replace(baked, "{" + name + "}", 1)
        setattr(card, field, text)

    # (3) a declared control input records the label the build actually showed
    observed: dict[str, str] = {}
    for step in steps:
        literal = _control_label(step, start_state)
        if literal is None:
            continue
        for name in declared:
            if name in (card.intent or "") + (card.preconditions or "") + (card.postconditions or "") + (card.effects_outputs or ""):
                observed.setdefault(name, literal)

    if not added and not observed:
        return card
    card.inputs = [
        _with_observed_label(item, observed) for item in card.inputs
    ] + added
    return card


def _contract_trace_value(
    step: Step, text: str, start_state: str = ""
) -> str | None:
    """A value this step carried that the contract now writes literally.

    The candidates are the values a step touched: a ``text=``/``desc=``
    target, or the value it typed.  A candidate is this run's data -- and so
    belongs in the contract as ``{item_label}`` rather than a literal -- when
    it appears in the contract *and* the launch screen already showed it as
    content.  A resource id names a widget, never data.
    """
    candidates: list[str] = []
    match = _TARGET_VALUE_RE.search(step.target)
    if match:
        value = match.group("value").strip()
        if value and ":id/" not in value and not value.startswith("resourceId="):
            candidates.append(value)
    if step.args and step.args.strip():
        candidates.append(step.args.strip())

    for value in candidates:
        if value and value in text and _screen_shows_text(start_state, value):
            return value
    return None


def _with_observed_label(declaration: str, observed: dict[str, str]) -> str:
    """Record the label the build showed for a declared control input.

    An optional input carries its observed value in the declaration itself
    (``label (optional): ...; observed: 'Delete note'``).  A control the
    build names is optional: the caller may pass a different label, and the
    trace's own label is what to use when it does not.
    """
    name = declaration.split()[0] if declaration.split() else ""
    label = observed.get(name)
    if not label:
        return declaration
    text = re.sub(r"\s*\((required|optional)\)", " (optional)", declaration, count=1)
    return f"{text}; observed: {label!r}"


def _trace_value(step: Step, line: str, start_state: str = "") -> str | None:
    """The trace's own data value that this step line hard-codes, if any.

    A tap names its object two ways.  ``text=bench_new.txt`` names a value
    the run's start screen displays -- the file this run happened to touch --
    and that is data: the card must take it as an input.  ``desc=Delete``
    names a control the screen offers -- every run of this function taps
    Delete -- and that is the function's own vocabulary, so it stays literal.

    The start screen tells the two apart: a value it shows as content is
    this run's data, while a value that only a screen the function itself
    opened reveals is the build's wording for a control.
    """
    match = _TARGET_VALUE_RE.search(step.target)
    if not match:
        return None
    value = match.group("value").strip()
    if not value or value not in line:
        return None
    # A resource id names the widget, not the data the run supplied.
    if ":id/" in value or value.startswith("resourceId="):
        return None
    if not start_state or not _screen_shows_text(start_state, value):
        return None
    return value


def _control_label(step: Step, start_state: str = "") -> str | None:
    """The label of the control this step tapped, if the trace names one.

    The mirror of ``_trace_value``: a tap's target is data when the run's
    start screen shows that value as content -- it is the file, the note,
    the folder this run happened to work on.  A value the start screen does
    not show is a control the screen offered: the build's own wording
    ("Delete note", "More options"), which no goal can supply.  A card that
    writes such a label as a caller input makes the binder guess it, and the
    guess cannot be checked against the build.
    """
    match = _TARGET_VALUE_RE.search(step.target)
    if not match:
        return None
    value = match.group("value").strip()
    if not value or ":id/" in value or value.startswith("resourceId="):
        return None
    # Without the launch screen there is nothing to compare against, and
    # guessing "vocabulary" would record a run's own data as the build's
    # wording.
    if not start_state or _screen_shows_text(start_state, value):
        return None
    return value


def _screen_shows_text(screen: str, value: str) -> bool:
    """Whether the screen displays this value as content, not as a label.

    Android puts what the user sees in ``text`` and a control's accessibility
    label in ``desc``/``content-desc``.  A launch screen that shows the value
    as ``text`` is showing this run's data -- the note, the file, the folder
    it starts from.  A value that appears only as a ``desc`` is a control's
    name, which the build owns however early it appears.
    """
    for line in (screen or "").splitlines():
        if value not in line:
            continue
        if re.search(
            rf"\btext=['\"]?{re.escape(value)}", line
        ):
            return True
    return False


def _render_steps(steps: list[Step]) -> str:
    return "\n".join(
        f"{index}. action={step.action!r} target={step.target!r} "
        f"args={step.args!r} before={step.before_state!r} "
        f"after={step.after_state!r}"
        for index, step in enumerate(steps)
    )


def _fallback_episode(trace: Trace) -> list[dict[str, Any]]:
    return [
        {
            "start": 0,
            "end": len(trace.steps) - 1,
            "name": f"{trace.app}_task",
            "intent": trace.goal or f"perform the traced task in {trace.app}",
        }
    ]


class CardMiner:
    """LLM-driven trace segmentation and function-card drafting."""

    def __init__(self, llm: LLMClient, cards: CardStore) -> None:
        self.llm = llm
        self.cards = cards

    def _validate(
        self, episodes: Any, trace: Trace
    ) -> list[dict[str, Any]] | None:
        if not isinstance(episodes, list) or not episodes:
            return None
        step_count = len(trace.steps)
        parsed: list[dict[str, Any]] = []
        for index, item in enumerate(episodes):
            if not isinstance(item, dict):
                return None
            start = item.get("start")
            end = item.get("end")
            if (
                type(start) is not int
                or type(end) is not int
                or start < 0
                or end < start
                or end >= step_count
            ):
                return None
            name = str(item.get("name") or f"{trace.app}_episode_{index}").strip()
            if not name:
                return None
            intent = str(item.get("intent") or name).strip()
            parsed.append(
                {
                    "start": start,
                    "end": end,
                    "name": name,
                    "intent": intent,
                }
            )
        parsed.sort(key=lambda episode: episode["start"])
        for previous, current in zip(parsed, parsed[1:]):
            if current["start"] <= previous["end"]:
                return None
        return parsed

    def segment(self, trace: Trace) -> list[dict[str, Any]]:
        if not trace.steps:
            return []
        prompt = (
            f"App: {trace.app}\nGoal: {trace.goal or 'unknown'}\n"
            f"Trace steps:\n{_render_steps(trace.steps)}\n\n"
            "Split this trace into user-level function episodes. "
            "Return JSON with inclusive step indices."
        )
        try:
            data = self.llm.complete_json(prompt, _SEGMENT_SCHEMA)
        except LLMParseError as exc:
            logger.warning("segmentation parse failed: %s", exc)
            return _fallback_episode(trace)
        episodes = data.get("episodes") if isinstance(data, dict) else None
        parsed = self._validate(episodes, trace)
        if parsed is None:
            logger.warning("segmentation boundaries invalid; using one episode")
            return _fallback_episode(trace)
        return parsed

    def _enrich(
        self, card: FunctionCard, trace: Trace, steps: list[Step]
    ) -> FunctionCard:
        if trace.trace_id not in card.evidence:
            card.evidence.append(trace.trace_id)
        if card.attempt_count == 0:
            card.attempt_count = 1
            card.success_count = (
                1 if all(step.success for step in steps) else 0
            )
        return card

    def draft(
        self, episode: dict[str, Any], trace: Trace
    ) -> FunctionCard | None:
        """Draft one card, or None when the model produced no contract.

        There is no fallback card.  A card built from the trace's actions is
        a transcript with a name, not a contract: it has no intent, no
        preconditions and no postconditions, so the planner can only replay
        it.  An episode the model cannot describe is skipped, and ``mine``
        says which trace it skipped.
        """
        start = episode["start"]
        end = episode["end"]
        steps = trace.steps[start : end + 1]
        prompt = (
            f"{_CARD_PROMPT}\n\nEpisode: {episode}\n"
            f"Observed steps:\n{_render_steps(steps)}\n"
            f"Trace evidence: {trace.trace_id}"
        )
        try:
            raw = self.llm.complete(
                prompt, system="You write precise mobile GUI function cards."
            )
            card = parse_card(_strip_fence(raw))
        except (CardParseError, LLMParseError) as exc:
            logger.warning(
                "card draft for %s produced no contract: %s",
                trace.trace_id,
                exc,
            )
            return None
        return self._enrich(
            _ground_contract(card, steps, trace.start_state), trace, steps
        )

    def mine(self, trace: Trace) -> CardPatch:
        if not trace.steps:
            return CardPatch()

        existing = self.cards.all()
        new_cards: list[FunctionCard] = []
        updates: list[dict[str, Any]] = []
        segments: list[dict[str, Any]] = []

        for episode in self.segment(trace):
            card = self.draft(episode, trace)
            steps = trace.steps[episode["start"] : episode["end"] + 1]
            succeeded = all(step.success for step in steps)

            if card is None:
                logger.warning(
                    "skipping episode %r of trace %s: no contract drafted",
                    episode.get("name"),
                    trace.trace_id,
                )
                continue
            if card.name in existing:
                old = existing[card.name]
                evidence = list(old.evidence)
                if trace.trace_id not in evidence:
                    evidence.append(trace.trace_id)
                updates.append(
                    {
                        "name": card.name,
                        "fields": {
                            "evidence": evidence,
                            "success_count": old.success_count
                            + (1 if succeeded else 0),
                            "attempt_count": old.attempt_count + 1,
                        },
                    }
                )
            else:
                duplicate = next(
                    (
                        candidate
                        for candidate in new_cards
                        if candidate.name == card.name
                    ),
                    None,
                )
                if duplicate is None:
                    new_cards.append(card)
                else:
                    for item in card.evidence:
                        if item not in duplicate.evidence:
                            duplicate.evidence.append(item)
                    duplicate.success_count += card.success_count
                    duplicate.attempt_count += card.attempt_count

            segments.append(
                {
                    "trace_id": trace.trace_id,
                    "start": episode["start"],
                    "end": episode["end"],
                    "card": card.name,
                }
            )

        return CardPatch(
            new_cards=new_cards, updates=updates, segments=segments
        )

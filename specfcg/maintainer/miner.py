"""Segment traces into user-level functions and draft function cards."""

from __future__ import annotations

import logging
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
_CARD_PROMPT = (
    "Write one reusable Markdown function card for this user-level episode. "
    "Generalize trace-specific values: declare them as named inputs and "
    "refer to them as {name} in Steps, Intent, and Postconditions. Do not "
    "bake the single observed values into the card, and do not mention "
    "unrelated existing data from the trace. "
    "Use exactly these headings, each followed by a colon: **Intent**, "
    "**Inputs**, **Preconditions**, **Postconditions**, **Effects/Outputs**, "
    "**Steps**, **Evidence**. "
    "Write Inputs as one bullet per parameter in the form "
    "'- name (required|optional): description'. "
    "The first line must be '# <function_name>' using a reusable "
    "snake_case name. Steps are numbered and must be reusable actions, not "
    "a transcript of this one run. Keep one physical UI action per step: if "
    "the trace pressed Back twice, write two Back steps instead of "
    "'repeat as needed'; if it pressed Enter or the keyboard Search key, "
    "write that as its own step. Name the concrete resource id or visible label "
    "for each control shown in the trace. Write Evidence exactly as "
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

    def _fallback_card(
        self, episode: dict[str, Any], trace: Trace, steps: list[Step]
    ) -> FunctionCard:
        return FunctionCard(
            name=str(episode["name"]),
            intent=str(episode.get("intent", "")),
            inputs=[],
            preconditions="",
            postconditions="",
            effects_outputs="",
            steps=[f"{step.action} {step.target}".strip() for step in steps],
            evidence=[trace.trace_id],
            success_count=1 if all(step.success for step in steps) else 0,
            attempt_count=1,
        )

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
    ) -> FunctionCard:
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
            logger.warning("card draft parse failed: %s", exc)
            return self._fallback_card(episode, trace, steps)
        return self._enrich(card, trace, steps)

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

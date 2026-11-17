"""Keyword prefilter plus LLM confirmation for card retrieval."""

from __future__ import annotations

import re

from specfcg.llm.client import LLMClient, LLMParseError
from specfcg.models import FunctionCard, Goal

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in _TOKEN_RE.findall(text.lower())
        if len(token) > 2
    }


class CardRetriever:
    def __init__(self, llm: LLMClient, top_k: int = 20) -> None:
        self.llm = llm
        self.top_k = top_k

    def retrieve(
        self, goal: Goal, cards: dict[str, FunctionCard]
    ) -> list[str]:
        names = list(cards)
        if len(names) <= self.top_k:
            return names

        goal_tokens = _tokens(goal.description)

        def score(name: str) -> int:
            card = cards[name]
            return len(
                goal_tokens & _tokens(f"{card.name} {card.intent}")
            )

        ranked = sorted(names, key=lambda name: (-score(name), name))
        limit = max(1, self.top_k)
        candidates = ranked[:limit]

        lines = "\n".join(
            f"- {name}: {cards[name].intent}" for name in candidates
        )
        prompt = (
            f"Goal: {goal.description}\nCandidates:\n{lines}\n\n"
            "Which cards are relevant to the goal? Keep only names from "
            "the candidate list."
        )
        try:
            data = self.llm.complete_json(prompt, '{"keep": ["name"]}')
        except LLMParseError:
            return candidates

        raw_keep = data.get("keep") if isinstance(data, dict) else None
        if not isinstance(raw_keep, list):
            return candidates
        keep = {str(name) for name in raw_keep}
        # The model may add semantic recall, but it must not delete a card
        # whose own name and intent share the goal's words: that card is
        # evidence, and dropping it leaves the planner with no route the
        # graph already had.
        literal = {name for name in candidates if score(name) > 0}
        filtered = [
            name for name in candidates if name in keep or name in literal
        ]
        return filtered or candidates

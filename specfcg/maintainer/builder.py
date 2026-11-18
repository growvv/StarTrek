"""Infer sequence and semantic edges between function cards."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from specfcg.llm.client import LLMClient, LLMParseError
from specfcg.models import Edge, FunctionCard

logger = logging.getLogger(__name__)

_EDGE_SCHEMA = (
    '{"edges": [{"from": "create_note", "to": "share_note", '
    '"type": "enables|dataflow", "description": "why the edge exists"}], '
    '"same_function": [["create_note", "add_note"]]}'
)


@dataclass
class SemanticResult:
    """What one semantic call returned: edges, and groups of same function.

    The groups are a model judgement, not a measurement: with the action
    lists gone there is no deterministic oracle for "same function".  They
    are reported for a person to inspect and never merged automatically.
    """

    edges: list[Edge] = field(default_factory=list)
    same_function: list[list[str]] = field(default_factory=list)


class EdgeBuilder:
    """Builds FCG edges from observed episodes and card contracts."""

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm

    @staticmethod
    def _merge_edges(edges: list[Edge]) -> list[Edge]:
        merged: list[Edge] = []
        index: dict[tuple[str, str, str], Edge] = {}
        for edge in edges:
            key = (edge.from_card, edge.to_card, edge.type)
            if key in index:
                existing = index[key]
                if edge.description:
                    existing.description = edge.description
                for item in edge.evidence:
                    if item not in existing.evidence:
                        existing.evidence.append(item)
                continue
            copy = Edge(
                from_card=edge.from_card,
                to_card=edge.to_card,
                type=edge.type,
                description=edge.description,
                evidence=list(edge.evidence),
            )
            index[key] = copy
            merged.append(copy)
        return merged

    def _sequence_edges(
        self,
        cards: dict[str, FunctionCard],
        segments: list[dict[str, Any]],
    ) -> list[Edge]:
        by_trace: dict[str, list[dict[str, Any]]] = {}
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            trace_id = segment.get("trace_id")
            card = segment.get("card")
            start = segment.get("start")
            if (
                not isinstance(trace_id, str)
                or not isinstance(card, str)
                or type(start) is not int
                or card not in cards
            ):
                continue
            by_trace.setdefault(trace_id, []).append(segment)

        edges: list[Edge] = []
        for trace_id, episodes in by_trace.items():
            episodes.sort(key=lambda episode: episode["start"])
            for previous, current in zip(episodes, episodes[1:]):
                if previous["card"] == current["card"]:
                    continue
                edges.append(
                    Edge(
                        from_card=str(previous["card"]),
                        to_card=str(current["card"]),
                        type="sequence",
                        description=(
                            f"Observed after {previous['card']} "
                            f"in trace {trace_id}."
                        ),
                        evidence=[trace_id],
                    )
                )
        return self._merge_edges(edges)

    def sequence_edges(
        self,
        cards: dict[str, FunctionCard],
        segments: list[dict[str, Any]],
    ) -> list[Edge]:
        """Sequence edges from observed episodes; makes no LLM call."""
        return self._sequence_edges(cards, segments)

    def infer_semantic(
        self, cards: dict[str, FunctionCard]
    ) -> SemanticResult:
        if len(cards) < 2:
            return SemanticResult()
        card_lines = "\n".join(
            f"- {name}: intent={card.intent!r}; "
            f"inputs={card.inputs!r}; "
            f"preconditions={card.preconditions!r}; "
            f"postconditions={card.postconditions!r}; "
            f"outputs={card.effects_outputs!r}"
            for name, card in cards.items()
        )
        prompt = (
            f"Function cards:\n{card_lines}\n\n"
            "Infer directed semantic edges between these user-level "
            "functions. Use type 'enables' when one function satisfies the "
            "preconditions of another, or 'dataflow' when an output of one "
            "can supply an input of another (for example a note title "
            "created by one card and used by another). Skip unrelated "
            "pairs.\n\n"
            "Also list groups of cards that describe the SAME user-level "
            "function, as same_function: a list of lists of card names. "
            "A group must name at least two cards that exist above, and a "
            "card belongs to at most one group. Use [] when there are none."
        )
        try:
            data = self.llm.complete_json(prompt, _EDGE_SCHEMA)
        except LLMParseError as exc:
            logger.warning("semantic edge inference failed: %s", exc)
            return SemanticResult()

        raw_edges = data.get("edges") if isinstance(data, dict) else None
        if not isinstance(raw_edges, list):
            raw_edges = []

        edges: list[Edge] = []
        for item in raw_edges:
            if not isinstance(item, dict):
                continue
            from_card = item.get("from")
            to_card = item.get("to")
            edge_type = item.get("type")
            if (
                not isinstance(from_card, str)
                or not isinstance(to_card, str)
                or not isinstance(edge_type, str)
                or from_card not in cards
                or to_card not in cards
                or from_card == to_card
                or edge_type not in {"enables", "dataflow"}
            ):
                continue
            evidence = item.get("evidence") or []
            if not isinstance(evidence, list):
                evidence = [evidence]
            edges.append(
                Edge(
                    from_card=str(from_card),
                    to_card=str(to_card),
                    type=edge_type,
                    description=str(item.get("description", "")),
                    evidence=[str(value) for value in evidence],
                )
            )
        return SemanticResult(
            edges=self._merge_edges(edges),
            same_function=self._same_function(
                data.get("same_function") if isinstance(data, dict) else None,
                cards,
            ),
        )

    @staticmethod
    def _same_function(
        raw: Any, cards: dict[str, FunctionCard]
    ) -> list[list[str]]:
        """Keep only real groups: two or more known, distinct cards."""
        if not isinstance(raw, list):
            return []
        groups: list[list[str]] = []
        seen: set[frozenset[str]] = set()
        for item in raw:
            if not isinstance(item, list):
                continue
            names = [
                name
                for name in item
                if isinstance(name, str) and name in cards
            ]
            # Preserve the model's order while dropping duplicates.
            unique = list(dict.fromkeys(names))
            if len(unique) < 2:
                continue
            key = frozenset(unique)
            if key in seen:
                continue
            seen.add(key)
            groups.append(unique)
        return groups

    def build(
        self,
        cards: dict[str, FunctionCard],
        segments: list[dict[str, Any]],
    ) -> SemanticResult:
        semantic = self.infer_semantic(cards)
        return SemanticResult(
            edges=self._merge_edges(
                self._sequence_edges(cards, segments) + semantic.edges
            ),
            same_function=semantic.same_function,
        )

"""Infer sequence and semantic edges between function cards."""

from __future__ import annotations

import logging
from typing import Any

from specfcg.llm.client import LLMClient, LLMParseError
from specfcg.models import Edge, FunctionCard

logger = logging.getLogger(__name__)

_EDGE_SCHEMA = (
    '{"edges": [{"from": "create_note", "to": "share_note", '
    '"type": "enables|dataflow", "description": "why the edge exists"}]}'
)


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
    ) -> list[Edge]:
        if len(cards) < 2:
            return []
        card_lines = "\n".join(
            f"- {name}: intent={card.intent!r}; "
            f"preconditions={card.preconditions!r}; "
            f"postconditions={card.postconditions!r}; "
            f"outputs={card.effects_outputs!r}"
            for name, card in cards.items()
        )
        prompt = (
            f"Function cards:\n{card_lines}\n\n"
            "Infer directed semantic edges between these user-level "
            "functions. Use type 'enables' when one function satisfies the "
            "preconditions of another, or 'dataflow' when output of one is "
            "input to another. Skip unrelated pairs."
        )
        try:
            data = self.llm.complete_json(prompt, _EDGE_SCHEMA)
        except LLMParseError as exc:
            logger.warning("semantic edge inference failed: %s", exc)
            return []

        raw_edges = data.get("edges") if isinstance(data, dict) else None
        if not isinstance(raw_edges, list):
            return []

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
        return self._merge_edges(edges)

    def build(
        self,
        cards: dict[str, FunctionCard],
        segments: list[dict[str, Any]],
    ) -> list[Edge]:
        return self._merge_edges(
            self._sequence_edges(cards, segments) + self.infer_semantic(cards)
        )

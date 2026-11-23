"""Evaluation metrics for generated GUI tests and the FCG."""

from __future__ import annotations

from collections.abc import Iterable

from specfcg.models import Graph, RunResult

EdgeKey = tuple[str, str, str]


def completion_rate(results: list[RunResult]) -> float:
    if not results:
        return 0.0
    return sum(1 for result in results if result.success) / len(results)


def action_accuracy(results: list[RunResult]) -> float:
    total = 0
    successful = 0
    for result in results:
        for step in result.step_results:
            if not isinstance(step, dict):
                continue
            total += 1
            if step.get("success"):
                successful += 1
    return successful / total if total else 0.0


def path_recall(
    graph: Graph, held_out: list[list[str]]
) -> float:
    if not held_out:
        return 0.0
    edges = {(edge.from_card, edge.to_card) for edge in graph.edges}
    recalled = 0
    for path in held_out:
        if all(
            pair in edges for pair in zip(path, path[1:])
        ):
            recalled += 1
    return recalled / len(held_out)


def coverage(
    graph: Graph,
    executed_cards: Iterable[str],
    executed_edges: Iterable[EdgeKey],
) -> dict[str, float]:
    card_names = set(graph.cards)
    edge_keys = {
        (edge.from_card, edge.to_card, edge.type)
        for edge in graph.edges
    }
    node = (
        len(card_names & set(executed_cards)) / len(card_names)
        if card_names
        else 0.0
    )
    edge = (
        len(edge_keys & set(executed_edges)) / len(edge_keys)
        if edge_keys
        else 0.0
    )
    return {"node": node, "edge": edge}

"""Goal-directed BFS/DFS/A* over the Function Contract Graph."""

from __future__ import annotations

import heapq
import itertools
from collections import deque
from typing import Callable, Literal

from specfcg.models import EDGE_PRIORITY, Graph


def _neighbors(graph: Graph, name: str) -> list[str]:
    edges = [
        edge for edge in graph.outgoing(name) if edge.to_card in graph.cards
    ]
    edges.sort(key=lambda edge: EDGE_PRIORITY.index(edge.type))
    result: list[str] = []
    seen: set[str] = set()
    for edge in edges:
        if edge.to_card not in seen:
            seen.add(edge.to_card)
            result.append(edge.to_card)
    return result


def search(
    graph: Graph,
    start: str | None,
    can_execute: Callable[[str], bool],
    is_goal: Callable[[str], bool],
    strategy: Literal["bfs", "dfs", "astar"] = "bfs",
    max_depth: int = 8,
    heuristic: Callable[[str], float] | None = None,
) -> list[str] | None:
    """Return a card path from an entry point to a goal card, or None.

    `start=None` seeds the search from entry cards (no incoming edges), so a
    plan is always grounded in a capability that needs no predecessor. An
    explicit `start` may name any card. LLM predicates are cached for the
    duration of one search because the external state does not change.
    """
    if start is not None:
        starts = [start]
    else:
        starts = graph.entry_cards()

    execute_cache: dict[str, bool] = {}
    goal_cache: dict[str, bool] = {}

    def executable(card: str) -> bool:
        if card not in execute_cache:
            execute_cache[card] = bool(can_execute(card))
        return execute_cache[card]

    def goal(card: str) -> bool:
        if card not in goal_cache:
            goal_cache[card] = bool(is_goal(card))
        return goal_cache[card]

    if strategy == "bfs":
        frontier: deque[list[str]] = deque()
        visited = set(starts)
        for candidate in starts:
            frontier.append([candidate])
        while frontier:
            path = frontier.popleft()
            card = path[-1]
            if not executable(card):
                continue
            if goal(card):
                return path
            if len(path) >= max_depth:
                continue
            for neighbor in _neighbors(graph, card):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                frontier.append(path + [neighbor])
        return None

    if strategy == "dfs":
        stack: list[list[str]] = [
            [candidate] for candidate in reversed(starts)
        ]
        visited = set(starts)
        while stack:
            path = stack.pop()
            card = path[-1]
            if not executable(card):
                continue
            if goal(card):
                return path
            if len(path) >= max_depth:
                continue
            for neighbor in reversed(_neighbors(graph, card)):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                stack.append(path + [neighbor])
        return None

    if strategy == "astar":
        score = heuristic or (lambda _card: 0.0)
        counter = itertools.count()
        heap: list[tuple[float, int, int, list[str]]] = []
        visited = set(starts)
        for candidate in starts:
            heapq.heappush(
                heap,
                (
                    1 + score(candidate),
                    next(counter),
                    1,
                    [candidate],
                ),
            )
        while heap:
            _priority, _tie, cost, path = heapq.heappop(heap)
            card = path[-1]
            if not executable(card):
                continue
            if goal(card):
                return path
            if len(path) >= max_depth:
                continue
            for neighbor in _neighbors(graph, card):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                next_cost = cost + 1
                heapq.heappush(
                    heap,
                    (
                        next_cost + score(neighbor),
                        next(counter),
                        next_cost,
                        path + [neighbor],
                    ),
                )
        return None

    raise ValueError(f"unknown search strategy: {strategy}")

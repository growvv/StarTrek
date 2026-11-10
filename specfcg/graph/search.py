"""Goal-directed BFS/DFS/A* over the Function Contract Graph."""

from __future__ import annotations

import heapq
import itertools
from collections import deque
from typing import Callable, Literal

from specfcg.models import EDGE_PRIORITY, Graph


_TRANSITIONS = {"enables", "sequence"}


def _neighbors(graph: Graph, name: str) -> list[str]:
    """Return cards reachable by an execution edge.

    `dataflow` only says a predecessor's output can supply a successor's
    input; it says nothing about the successor's preconditions, so a card
    connected only by dataflow is not executable yet. `enables` and
    `sequence` are the execution transitions.
    """
    edges = [
        edge
        for edge in graph.outgoing(name)
        if edge.to_card in graph.cards and edge.type in _TRANSITIONS
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
    is_goal: Callable[[str, list[str]], bool],
    strategy: Literal["bfs", "dfs", "astar"] = "bfs",
    max_depth: int = 8,
    heuristic: Callable[[str], float] | None = None,
    *,
    starts: list[str] | None = None,
) -> list[str] | None:
    """Return a card path from a seed card to a goal card, or None.

    Seeds are, in priority order: `starts` when given, `start` when given,
    otherwise the graph's entry cards (no incoming edges). Seeding from an
    explicit list lets the planner start from any card whose preconditions
    currently hold, which matters for graphs with cycles. Only the first
    card of a path is checked against the current UI state: every later
    card is reached over an FCG edge, and that edge is the contract saying
    its predecessor provides what it needs. `is_goal` receives the whole
    path because a multi-card plan can satisfy a goal that no single card
    satisfies. Both predicates are cached for the duration of one search
    because the external state does not change.
    """
    if starts is not None:
        seeds = [name for name in starts if name in graph.cards]
    elif start is not None:
        seeds = [start]
    else:
        seeds = graph.entry_cards()

    execute_cache: dict[str, bool] = {}
    goal_cache: dict[tuple[str, ...], bool] = {}

    def executable(card: str) -> bool:
        if card not in execute_cache:
            execute_cache[card] = bool(can_execute(card))
        return execute_cache[card]

    def goal(card: str, path: list[str]) -> bool:
        key = tuple(path)
        if key not in goal_cache:
            goal_cache[key] = bool(is_goal(card, path))
        return goal_cache[key]

    if strategy == "bfs":
        frontier: deque[list[str]] = deque()
        visited = set(seeds)
        for candidate in seeds:
            frontier.append([candidate])
        while frontier:
            path = frontier.popleft()
            card = path[-1]
            if len(path) == 1 and not executable(card):
                continue
            if goal(card, path):
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
            [candidate] for candidate in reversed(seeds)
        ]
        visited = set(seeds)
        while stack:
            path = stack.pop()
            card = path[-1]
            if len(path) == 1 and not executable(card):
                continue
            if goal(card, path):
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
        visited = set(seeds)
        for candidate in seeds:
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
            if len(path) == 1 and not executable(card):
                continue
            if goal(card, path):
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

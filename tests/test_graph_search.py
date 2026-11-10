import pytest

from specfcg.graph.search import search
from specfcg.models import Edge, FunctionCard, Graph


def test_bfs_finds_shortest_path(simple_graph):
    path = search(
        simple_graph,
        None,
        lambda c: True,
        lambda c, _path: c == "C",
        "bfs",
    )
    assert path == ["A", "C"]


def test_cycle_does_not_loop(simple_graph):
    assert (
        search(
            simple_graph,
            "A",
            lambda c: True,
            lambda c, _path: c == "Z",
            "bfs",
        )
        is None
    )


def test_max_depth_respected(long_chain):
    assert (
        search(
            long_chain,
            None,
            lambda c: True,
            lambda c, _path: c == "Z",
            "dfs",
            max_depth=3,
        )
        is None
    )


def test_astar_uses_heuristic(simple_graph):
    path = search(
        simple_graph,
        None,
        lambda c: True,
        lambda c, _path: c == "C",
        "astar",
        heuristic=lambda c: 0.0,
    )
    assert path is not None and path[-1] == "C"


def test_can_execute_gates_expansion(simple_graph):
    path = search(
        simple_graph,
        None,
        lambda c: c != "A",
        lambda c, _path: c == "C",
        "bfs",
    )
    assert path is None


@pytest.mark.parametrize("strategy", ["bfs", "dfs", "astar"])
def test_trusts_edge_successors_after_executable_entry(
    simple_graph, strategy
):
    path = search(
        simple_graph,
        None,
        lambda card: card == "A",
        lambda card, _path: card == "C",
        strategy,
    )
    assert path == ["A", "C"]


@pytest.mark.parametrize("strategy", ["bfs", "dfs", "astar"])
def test_entry_card_still_must_be_executable(simple_graph, strategy):
    assert (
        search(
            simple_graph,
            None,
            lambda card: False,
            lambda card, _path: card == "C",
            strategy,
        )
        is None
    )


def test_is_goal_receives_the_planned_path(simple_graph):
    seen: list[tuple[str, list[str]]] = []

    def is_goal(card, path):
        seen.append((card, list(path)))
        return card == "C"

    search(simple_graph, None, lambda c: True, is_goal, "bfs")
    assert ("A", ["A"]) in seen
    assert ("C", ["A", "C"]) in seen


def test_dataflow_only_edges_do_not_authorize_execution():
    graph = Graph(
        cards={
            "A": FunctionCard(
                name="A", intent="a", inputs=[], preconditions="",
                postconditions="", effects_outputs="output",
                steps=[],
            ),
            "B": FunctionCard(
                name="B", intent="b", inputs=["value"], preconditions="",
                postconditions="", effects_outputs="", steps=[],
            ),
        },
        edges=[Edge(from_card="A", to_card="B", type="dataflow")],
    )

    assert (
        search(
            graph,
            None,
            lambda c: True,
            lambda c, _path: c == "B",
            "bfs",
        )
        is None
    )


def test_explicit_starts_seed_search_outside_entry_cards(simple_graph):
    path = search(
        simple_graph,
        None,
        lambda c: True,
        lambda c, _path: c == "B",
        "bfs",
        starts=["B"],
    )
    assert path == ["B"]

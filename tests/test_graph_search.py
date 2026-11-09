from specfcg.graph.search import search


def test_bfs_finds_shortest_path(simple_graph):
    path = search(
        simple_graph, None, lambda c: True, lambda c: c == "C", "bfs"
    )
    assert path == ["A", "C"]


def test_cycle_does_not_loop(simple_graph):
    assert (
        search(
            simple_graph, "A", lambda c: True, lambda c: c == "Z", "bfs"
        )
        is None
    )


def test_max_depth_respected(long_chain):
    assert (
        search(
            long_chain,
            None,
            lambda c: True,
            lambda c: c == "Z",
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
        lambda c: c == "C",
        "astar",
        heuristic=lambda c: 0.0,
    )
    assert path is not None and path[-1] == "C"


def test_can_execute_gates_expansion(simple_graph):
    path = search(
        simple_graph, None, lambda c: c != "A", lambda c: c == "C", "bfs"
    )
    assert path is None

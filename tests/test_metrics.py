from __future__ import annotations

from dataclasses import replace

from specfcg.benchmark.metrics import (
    action_accuracy,
    completion_rate,
    coverage,
    path_recall,
)
from specfcg.models import Graph, RunResult


def test_completion_rate(successful_result, failed_result):
    assert (
        completion_rate([successful_result, failed_result]) == 0.5
    )


def test_completion_rate_empty():
    assert completion_rate([]) == 0.0


def test_action_accuracy(successful_result):
    assert action_accuracy([successful_result]) == 1.0


def test_action_accuracy_counts_partial_steps(
    successful_result, failed_result
):
    result = replace(
        successful_result,
        step_results=[
            {"success": True},
            {"success": False},
            {"success": True},
        ],
    )
    assert action_accuracy([result]) == 2 / 3


def test_action_accuracy_empty():
    assert action_accuracy([]) == 0.0


def test_path_recall(sample_graph):
    assert (
        path_recall(
            sample_graph, [["create_note", "share_note"]]
        )
        == 1.0
    )


def test_path_recall_averages_missing_paths(sample_graph):
    held_out = [
        ["create_note", "share_note"],
        ["share_note", "create_note"],
    ]
    assert path_recall(sample_graph, held_out) == 0.5


def test_path_recall_empty():
    assert path_recall(Graph(), []) == 0.0


def test_coverage_counts(sample_graph):
    cov = coverage(
        sample_graph,
        {"create_note"},
        {("create_note", "share_note", "enables")},
    )
    assert cov["node"] == 0.5
    assert cov["edge"] == 1.0


def test_coverage_empty_graph():
    assert coverage(Graph(), set(), set()) == {
        "node": 0.0,
        "edge": 0.0,
    }


def test_coverage_ignores_unknown_executed_edges(sample_graph):
    cov = coverage(
        sample_graph,
        {"missing"},
        {("missing", "create_note", "sequence")},
    )
    assert cov == {"node": 0.0, "edge": 0.0}

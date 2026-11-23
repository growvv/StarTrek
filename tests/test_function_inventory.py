"""A tool's own function list is a reference, never a denominator."""
from __future__ import annotations

import json
from pathlib import Path

from specfcg.datasets.function_inventory import (
    load_inventory,
    scale_summary,
)

FDG = {
    "FDG": [
        {
            "index": 0,
            "function_description": "Manage and view notes",
            "to_test": True,
            "core_logic": {"entry_page": "0"},
        },
        {
            "index": 1,
            "function_description": "Search notes",
            "data_in": "['notes']",
            "data_out": "['search interface']",
            "to_test": True,
        },
        {
            "index": 2,
            "function_description": "A helper page nobody tests",
            "to_test": False,
        },
    ]
}


def _build(tmp_path: Path, name: str = "App-1.0-#1") -> Path:
    d = tmp_path / "dataset" / name
    d.mkdir(parents=True)
    (d / "fdg.json").write_text(json.dumps(FDG), encoding="utf-8")
    return d


def test_the_list_is_read_with_its_descriptions_and_data(tmp_path):
    inventory = load_inventory(_build(tmp_path))

    assert inventory is not None
    assert inventory.total == 2  # the to_test=False entry is not counted
    search = inventory.functions[1]
    assert search.data_in == ["notes"]
    assert search.data_out == ["search interface"]


def test_the_inventory_declares_itself_an_answer_key(tmp_path):
    """Scoring against the compared tool's own graph measures name agreement.

    The list was produced by the tool this work is compared against, so using
    it as the denominator of "our graph covers 90%" would measure how closely
    two tools name the same functions — not coverage of the app.
    """
    inventory = load_inventory(_build(tmp_path))

    assert inventory.is_answer_key is True
    assert "funcDroid" in inventory.source


def test_a_build_without_the_file_has_no_inventory(tmp_path):
    """An empty list would make the build look like it has zero functions."""
    d = tmp_path / "dataset" / "App-2.0-#2"
    d.mkdir(parents=True)

    assert load_inventory(d) is None


def test_malformed_json_is_reported_as_no_inventory(tmp_path):
    d = tmp_path / "dataset" / "App-3.0-#3"
    d.mkdir(parents=True)
    (d / "fdg.json").write_text("{", encoding="utf-8")

    assert load_inventory(d) is None


def test_the_scale_summary_counts_builds_and_functions(tmp_path):
    _build(tmp_path, "App-1.0-#1")
    _build(tmp_path, "App-2.0-#2")

    summary = scale_summary(tmp_path / "dataset")

    assert summary["builds"] == 2
    assert summary["functions"] == 4
    assert summary["answer_key"] is True

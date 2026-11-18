"""The duplicate reader reports what the builder recorded, not a score."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "measure_duplicates", ROOT / "scripts" / "measure_duplicates.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _app(tmp_path: Path, groups: list) -> Path:
    app = tmp_path / "amaze"
    graph = app / "graph"
    graph.mkdir(parents=True)
    (graph / "same_function.json").write_text(
        json.dumps({"groups": groups}), encoding="utf-8"
    )
    return app


def test_the_reader_returns_the_groups_the_builder_wrote(tmp_path):
    app = _app(tmp_path, [["merge_notes", "merge_two_notes"], ["open_note"]])
    groups = _module().groups_for(app)
    assert groups == [["merge_notes", "merge_two_notes"]]


def test_an_app_without_the_file_reports_no_groups(tmp_path):
    app = tmp_path / "markor"
    (app / "graph").mkdir(parents=True)
    assert _module().groups_for(app) == []


def test_malformed_json_does_not_crash_the_reader(tmp_path):
    app = tmp_path / "x"
    (app / "graph").mkdir(parents=True)
    (app / "graph" / "same_function.json").write_text("{", encoding="utf-8")
    assert _module().groups_for(app) == []


def test_the_reader_prints_the_judgement_caveat(tmp_path, capsys):
    _app(tmp_path, [["a", "b"]])
    assert _module().main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "model judgements" in out
    assert "never merged" in out


def test_the_reader_finds_groups_in_the_nested_graph_layout(tmp_path):
    """`runs/mobileworld/<app>/graph` keeps its store in a nested `graph/`."""
    app = tmp_path / "omninotes"
    nested = app / "graph" / "graph"
    nested.mkdir(parents=True)
    (nested / "same_function.json").write_text(
        json.dumps({"groups": [["merge_notes", "merge_two_notes"]]}),
        encoding="utf-8",
    )
    assert _module().groups_for(app) == [["merge_notes", "merge_two_notes"]]

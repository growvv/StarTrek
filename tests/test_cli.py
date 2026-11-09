from __future__ import annotations

import json
from pathlib import Path

import yaml

from specfcg.cli import main
from specfcg.traces.recorder import trace_to_dict


def _config(tmp_path) -> tuple[Path, Path]:
    root = tmp_path / "data"
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump({"paths": {"root": str(root)}}),
        encoding="utf-8",
    )
    return path, root


def _trace_path(tmp_path, sample_trace) -> Path:
    path = tmp_path / "trace.json"
    path.write_text(
        json.dumps(trace_to_dict(sample_trace)),
        encoding="utf-8",
    )
    return path


def _mine(config_path, trace_path) -> int:
    return main(
        [
            "mine",
            "--config",
            str(config_path),
            "--trace",
            str(trace_path),
            "--fake-llm",
        ]
    )


def test_cli_mine_creates_cards(tmp_path, sample_trace, capsys):
    config_path, root = _config(tmp_path)
    trace_path = _trace_path(tmp_path, sample_trace)

    code = _mine(config_path, trace_path)

    assert code == 0
    assert (root / "cards" / "create_note.md").exists()


def test_cli_plan_prints_json(tmp_path, sample_trace, capsys):
    config_path, _root = _config(tmp_path)
    _mine(config_path, _trace_path(tmp_path, sample_trace))
    capsys.readouterr()

    code = main(
        [
            "plan",
            "--config",
            str(config_path),
            "--goal",
            "create a note",
            "--state",
            "Notes list",
            "--fake-llm",
        ]
    )

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["path"] == ["create_note"]
    assert data["goal"]["description"] == "create a note"


def test_cli_execute_prints_result(tmp_path, sample_trace, capsys):
    config_path, _root = _config(tmp_path)
    _mine(config_path, _trace_path(tmp_path, sample_trace))
    capsys.readouterr()

    code = main(
        [
            "execute",
            "--config",
            str(config_path),
            "--goal",
            "create a note",
            "--state",
            "Notes list",
            "--fake-llm",
            "--fake-device",
        ]
    )

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["success"] is True
    assert data["goal_success"] is True


def test_cli_refine_prints_patch(tmp_path, sample_trace, capsys):
    config_path, _root = _config(tmp_path)
    _mine(config_path, _trace_path(tmp_path, sample_trace))
    capsys.readouterr()

    code = main(
        [
            "refine",
            "--config",
            str(config_path),
            "--goal",
            "create a note",
            "--state",
            "Notes list",
            "--fake-llm",
            "--fake-device",
        ]
    )

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["reason"] == "successful execution"


def test_cli_complete_prints_null_when_no_gap(tmp_path, capsys):
    config_path, _root = _config(tmp_path)

    code = main(
        [
            "complete",
            "--config",
            str(config_path),
            "--goal",
            "attach a photo",
            "--fake-llm",
        ]
    )

    assert code == 0
    assert capsys.readouterr().out.strip() == "null"


def test_cli_run_prints_summary(tmp_path, sample_trace, capsys):
    config_path, _root = _config(tmp_path)
    _mine(config_path, _trace_path(tmp_path, sample_trace))
    capsys.readouterr()

    code = main(
        [
            "run",
            "--config",
            str(config_path),
            "--goal",
            "create a note",
            "--state",
            "Notes list",
            "--fake-llm",
            "--fake-device",
        ]
    )

    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["success"] is True
    assert data["rounds"] == 1


def test_cli_build_graph_prints_edges(tmp_path, sample_trace, capsys):
    config_path, _root = _config(tmp_path)
    _mine(config_path, _trace_path(tmp_path, sample_trace))
    capsys.readouterr()

    code = main(
        [
            "build-graph",
            "--config",
            str(config_path),
            "--fake-llm",
        ]
    )

    assert code == 0
    assert isinstance(json.loads(capsys.readouterr().out), list)

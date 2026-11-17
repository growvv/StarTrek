from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "record_score", ROOT / "scripts" / "record_score.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_runs(root: Path) -> None:
    app = root / "omninotes"
    (app / "experiments").mkdir(parents=True)
    (app / "bench-specfcg").mkdir(parents=True)
    (app / "experiments" / "coverage.json").write_text(
        '{"covered": 23, "functions": 23, "score": 1.0}', encoding="utf-8"
    )
    (app / "bench-specfcg" / "summary.json").write_text(
        '{"agent": "specfcg", "rows": [{"success": true}, {"success": false}]}',
        encoding="utf-8",
    )


def test_recording_turns_the_saved_records_into_one_curve_point(tmp_path, capsys):
    runs = tmp_path / "runs"
    _write_runs(runs)
    history = runs / "score-history.json"

    code = _module().main(
        [
            "--runs",
            str(runs),
            "--history",
            str(history),
            "--label",
            "baseline",
        ]
    )

    assert code == 0
    points = json.loads(history.read_text(encoding="utf-8"))["points"]
    assert len(points) == 1
    assert points[0]["label"] == "baseline"
    assert points[0]["dims"]["graph"] == 100.0
    assert points[0]["dims"]["task"] == 50.0
    assert "综合" in capsys.readouterr().out


def test_recording_refuses_an_empty_run_directory(tmp_path, capsys):
    runs = tmp_path / "runs"
    runs.mkdir()

    code = _module().main(["--runs", str(runs), "--label", "baseline"])

    assert code == 2
    assert "no scored records" in capsys.readouterr().err

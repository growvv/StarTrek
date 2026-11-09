from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from specfcg.benchmark.cases import (
    load_apps,
    load_cases,
    load_goals,
)

REPO_ROOT = Path(__file__).parents[1]


def test_stage1_manifest_has_6_apps_60_cases_30_goals():
    apps = load_apps(REPO_ROOT / "benchmark" / "apps.yaml")
    cases = load_cases(REPO_ROOT / "benchmark" / "cases")
    goals = load_goals(REPO_ROOT / "benchmark" / "goals")

    assert len(apps) == 6
    assert len(cases) == 60
    assert len(goals) == 30
    assert all(app.version for app in apps)
    assert Counter(case.app for case in cases) == Counter(
        {app.name: 10 for app in apps}
    )
    assert Counter(goal.app for goal in goals) == Counter(
        {app.name: 5 for app in apps}
    )
    assert all(goal.assertions for goal in goals)


def test_run_stage1_fake_writes_report(tmp_path):
    output = tmp_path / "report.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_stage1.py",
            "--fake",
            "--limit",
            "3",
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert len(report["cases"]) == 3
    assert "completion_rate" in report
    assert "action_accuracy" in report
    assert "path_recall" in report
    assert "coverage" in report
    assert "cost" in report

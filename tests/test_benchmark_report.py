from __future__ import annotations

from specfcg.scoring.report import summarize


def _row(task_id: str, app: str, success: bool, failure=None, steps=5):
    return {
        "task_id": task_id,
        "app": app,
        "success": success,
        "failure_type": failure,
        "steps": steps,
        "max_steps": 20,
        "tags": [],
        "predicted_confidence": 0.8,
        "predicted_path": [],
        "reached_cards": [],
    }


def test_summarize_counts_success_and_failure_types():
    rows = [
        _row("a1", "omninotes", True),
        _row("a2", "omninotes", False, "step_limit"),
        _row("b1", "markor", False, "loop_detected"),
        _row("b2", "markor", False, "goal_oracle_failure"),
    ]
    summary = summarize(rows)
    assert summary["tasks"] == 4
    assert summary["success"] == 1
    assert summary["success_rate"] == 0.25
    assert summary["failure_types"] == {
        "step_limit": 1,
        "loop_detected": 1,
        "goal_oracle_failure": 1,
    }


def test_summarize_groups_by_app():
    rows = [
        _row("a1", "omninotes", True),
        _row("a2", "omninotes", False, "action_failure"),
        _row("b1", "markor", True),
    ]
    summary = summarize(rows)
    by_app = summary["by_app"]
    assert by_app["omninotes"]["tasks"] == 2
    assert by_app["omninotes"]["success"] == 1
    assert by_app["markor"]["success_rate"] == 1.0


def test_summarize_reports_mean_steps_and_predicted_confidence():
    rows = [
        _row("a1", "omninotes", True, steps=4),
        _row("a2", "omninotes", False, "step_limit", steps=20),
    ]
    summary = summarize(rows)
    assert summary["mean_steps"] == 12.0
    assert summary["mean_predicted_confidence"] == 0.8


def test_summarize_handles_no_rows():
    summary = summarize([])
    assert summary["tasks"] == 0
    assert summary["success_rate"] == 0.0
    assert summary["failure_types"] == {}

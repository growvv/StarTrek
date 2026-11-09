from __future__ import annotations

from specfcg.benchmark.cases import NLTestCase
from specfcg.benchmark.runner import Runner


def test_runner_collects_case_rows(successful_result):
    runner = Runner(lambda case_id: successful_result)

    rows = runner.run(
        [NLTestCase(id="c1", app="omninotes", text="create a note")]
    )

    assert rows == [
        {
            "case_id": "c1",
            "success": True,
            "goal_success": True,
            "steps": 2,
            "failure_type": None,
        }
    ]


def test_runner_calls_run_case_once_per_case(successful_result):
    seen: list[str] = []

    def run_case(case_id: str):
        seen.append(case_id)
        return successful_result

    cases = [
        NLTestCase(id="c1", app="omninotes", text="create a note"),
        NLTestCase(id="c2", app="omninotes", text="share a note"),
    ]

    rows = Runner(run_case).run(cases)

    assert seen == ["c1", "c2"]
    assert [row["case_id"] for row in rows] == ["c1", "c2"]


def test_runner_records_failure(failed_result):
    rows = Runner(lambda case_id: failed_result).run(
        [NLTestCase(id="c1", app="omninotes", text="create a note")]
    )

    assert rows[0]["success"] is False
    assert rows[0]["goal_success"] is False
    assert rows[0]["failure_type"] == "widget_failure"

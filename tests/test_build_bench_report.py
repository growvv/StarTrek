from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "build_bench_report", ROOT / "scripts" / "build_bench_report.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SELFOPT = {
    "rounds": 3,
    "completed": 2,
    "cards_added": 2,
    "cards_start": 10,
    "cards_end": 12,
    "covered_start": 7,
    "covered_end": 9,
    "total": 15,
    "curve": [7, 8, 9, 9],
    "records": [
        {
            "index": 1,
            "function": "open_map",
            "label": "Open the map view",
            "goal": "In the app, open the map view.",
            "cards_before": 10,
            "cards_after": 11,
            "covered_before": 7,
            "covered_after": 8,
            "added_cards": ["open_map"],
            "completed": True,
            "reason": "",
        },
        {
            "index": 2,
            "function": "open_settings",
            "label": "Open settings",
            "goal": "In the app, open settings.",
            "cards_before": 11,
            "cards_after": 12,
            "covered_before": 8,
            "covered_after": 9,
            "added_cards": ["open_settings"],
            "completed": True,
            "reason": "",
        },
        {
            "index": 3,
            "function": "filter_history",
            "label": "Filter history",
            "goal": "In the app, filter history.",
            "cards_before": 12,
            "cards_after": 12,
            "covered_before": 9,
            "covered_after": 9,
            "added_cards": [],
            "completed": False,
            "reason": "no card added",
        },
    ],
}


def test_selfopt_section_reports_the_coverage_curve_and_rounds():
    html = _module()._selfopt_section(SELFOPT)

    assert "自优化" in html
    assert "7 → 9" in html
    assert "2/3" in html
    assert "open_map" in html
    assert "filter_history" in html


def test_selfopt_section_is_empty_without_data():
    assert _module()._selfopt_section(None) == ""


SELFOPT_RECORD = {
    "app": "omninotes",
    "summary": {
        "rounds": 2,
        "completed": 1,
        "cards_added": 1,
        "cards_start": 9,
        "cards_end": 10,
        "covered_start": 8,
        "covered_end": 9,
        "total": 23,
        "curve": [8, 9, 9],
    },
    "rounds": [
        {
            "index": 1,
            "function": "create_checklist",
            "label": "Create a checklist note",
            "goal": "In the app, create a checklist note.",
            "added_cards": ["create_checklist_note"],
            "completed": True,
            "reason": "",
        },
        {
            "index": 2,
            "function": "delete_note",
            "label": "Delete a note",
            "goal": "In the app, delete a note.",
            "added_cards": [],
            "completed": False,
            "reason": "no completion",
        },
    ],
}


def test_selfopt_section_reads_the_record_the_runner_writes():
    """The runner writes summary + rounds; the page must read that shape.

    Read as the flat test fixture, a real run renders zero rounds and a
    zero-length curve -- the section looks like it ran and found nothing.
    """
    html = _module()._selfopt_section(SELFOPT_RECORD)

    assert "8 → 9" in html
    assert "1/2" in html
    assert "create_checklist_note" in html
    assert "delete_note" in html


def test_collect_prefers_the_complete_graph_and_falls_back_to_the_seed_run(tmp_path):
    """Probes and the self-optimization curve run on the seed graph.

    The seed run lives in seed-experiments/ because it measures a different
    graph; the page still has to find those records, or the probe and
    self-optimization sections vanish from a report whose data exists.
    """
    app = tmp_path / "omninotes"
    (app / "experiments").mkdir(parents=True)
    (app / "seed-experiments").mkdir(parents=True)
    (app / "experiments" / "coverage.json").write_text(
        '{"covered": 23, "functions": 23}', encoding="utf-8"
    )
    (app / "seed-experiments" / "probes.json").write_text(
        '{"calibration": {"probes": 6}}', encoding="utf-8"
    )
    (app / "seed-experiments" / "selfopt.json").write_text(
        '{"summary": {"rounds": 4}}', encoding="utf-8"
    )

    data = _module().collect(tmp_path)
    entry = data["apps"][0]

    assert entry["coverage"]["covered"] == 23
    assert entry["probes"]["calibration"]["probes"] == 6
    assert entry["selfopt"]["summary"]["rounds"] == 4


def test_overview_reads_the_selfopt_summary_written_by_the_runner():
    data = {
        "apps": [
            {
                "app": "markor",
                "coverage": {"covered": 17, "functions": 17, "score": 1.0},
                "random": {"score_union": 0.41},
                "probes": {"calibration": {"predicted": 0.45, "actual": 0.5, "probes": 6}},
                "selfopt": SELFOPT_RECORD,
            }
        ]
    }

    html = _module().render(data)

    assert "8→9" in html


HISTORY = [
    {
        "iteration": 0,
        "label": "baseline",
        "timestamp": "2026-11-12T00:00:00Z",
        "dims": {"graph": 100.0, "calibration": 84.0, "selfopt": 8.0, "task": 30.0},
        "control": {"random": 41.0},
        "overall": 55.5,
    },
    {
        "iteration": 1,
        "label": "planner-verification",
        "timestamp": "2026-11-12T01:00:00Z",
        "dims": {"graph": 100.0, "calibration": 86.0, "selfopt": 12.0, "task": 45.0},
        "control": {"random": 41.0},
        "overall": 60.8,
    },
]


def test_curve_section_draws_every_recorded_iteration():
    """The report's headline: one line per dimension over the iterations."""
    html = _module()._curve_section(HISTORY)

    assert "指标曲线" in html
    assert 'id="score-curve"' in html
    assert "baseline" in html
    assert "planner-verification" in html
    # the overall line and its two values are visible as text, not only as
    # geometry: 55.5 then 60.8
    assert "55.5" in html and "60.8" in html
    assert "图完整度" in html and "任务成功率" in html
    # every marker carries a native tooltip with its iteration and value
    assert html.count("<title>") >= len(HISTORY) * 4


def test_curve_section_handles_a_single_point():
    html = _module()._curve_section(HISTORY[:1])

    assert 'id="score-curve"' in html
    assert "polyline" not in html or "points=" in html
    assert "55.5" in html


def test_curve_section_is_empty_without_history():
    assert _module()._curve_section([]) == ""


def test_bench_rows_keep_the_final_screenshot_and_every_action(tmp_path):
    """Acceptance evidence: the screen the oracle judged, and the steps taken."""
    shots = tmp_path / "runs" / "omninotes" / "bench-specfcg" / "shots"
    shots.mkdir(parents=True)
    png = shots / "omni_create_note.png"
    png.write_bytes(b"png-bytes")
    data = {
        "apps": [
            {
                "app": "omninotes",
                "coverage": {},
                "shots": [str(png)],
                "bench": [
                    {
                        "agent": "specfcg",
                        "rows": [
                            {
                                "task_id": "omni_create_note",
                                "success": True,
                                "failure_type": None,
                                "steps": 1,
                                "max_steps": 20,
                                "reason": "ok",
                                "predicted_path": ["create_text_note"],
                                "actions": [
                                    {
                                        "action": "click",
                                        "target": "text=+",
                                        "args": "",
                                        "ok": True,
                                        "card": "create_text_note",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }

    html = _module().render(data, evidence_root=tmp_path / "evidence")

    assert "<img" in html
    assert "evidence/omninotes/omni_create_note.png" in html
    assert (tmp_path / "evidence" / "omninotes" / "omni_create_note.png").exists()
    assert "text=+" in html  # the per-step action table is rendered
    assert "create_text_note" in html


def test_report_links_the_constructed_graph_for_each_app():
    """The acceptance report shows the graph each metric was measured on.

    The graph page replays the construction journal; the report links it
    beside the card/edge counts so the picture is one click away.
    """
    data = {
        "apps": [
            {
                "app": "omninotes",
                "coverage": {"cards": 31, "edges": 193, "covered": 23, "functions": 23, "score": 1.0},
            }
        ]
    }

    html = _module().render(data)

    assert "构建的图" in html
    assert "../graph/omninotes.html" in html
    assert "31 张卡片 / 193 条边" in html


def test_report_is_linked_from_the_site():
    """The benchmark page is one of the project's reports.

    It is written to docs/reports/, so the site has to offer a link to it;
    otherwise the page exists only for someone who knows the URL.
    """
    source = (ROOT / "scripts" / "build_site.py").read_text(encoding="utf-8")

    assert "reports/mobileworld.html" in source


def test_bench_section_lists_failure_types_as_counts():
    """A failure taxonomy is read as "3 no_plan, 2 step_limit"."""
    data = {
        "apps": [
            {
                "app": "markor",
                "coverage": {},
                "bench": [
                    {
                        "agent": "specfcg",
                        "rows": [
                            {"task_id": "t1", "success": False, "failure_type": "no_plan", "steps": 0, "max_steps": 20, "reason": ""},
                            {"task_id": "t2", "success": False, "failure_type": "no_plan", "steps": 0, "max_steps": 20, "reason": ""},
                            {"task_id": "t3", "success": False, "failure_type": "step_limit", "steps": 20, "max_steps": 20, "reason": ""},
                        ],
                    }
                ],
            }
        ]
    }

    html = _module().render(data)

    assert "no_plan ×2" in html
    assert "step_limit ×1" in html
    assert "&quot;" not in html.split("失败类型")[1][:200]


def test_estimate_section_scores_each_dimension_from_the_records():
    """The estimated score is computed from the saved records, not typed in.

    Five dimensions, each 0-100 and each traceable to a record: graph
    completeness, how far unguided traversal gets, probe calibration error,
    self-optimization gain, and task success under the 20-step cap.
    """
    data = {
        "apps": [
            {
                "app": "markor",
                "coverage": {"covered": 17, "functions": 17, "score": 1.0},
                "random": {"score_union": 0.4},
                "probes": {"calibration": {"predicted": 0.45, "actual": 0.5, "probes": 6}},
                "selfopt": SELFOPT_RECORD,
                "bench": [
                    {
                        "agent": "specfcg",
                        "rows": [
                            {"task_id": "t1", "success": True, "failure_type": None, "steps": 3, "max_steps": 20, "reason": ""},
                            {"task_id": "t2", "success": False, "failure_type": "no_plan", "steps": 0, "max_steps": 20, "reason": ""},
                        ],
                    }
                ],
            }
        ]
    }

    html = _module().render(data)

    assert "估计打分" in html
    # graph 100, random 40, calibration 95, selfopt gain 1/17 -> 6, task 50
    assert "100" in html and "40" in html and "95" in html and "50" in html

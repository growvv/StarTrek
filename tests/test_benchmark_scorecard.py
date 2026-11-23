from __future__ import annotations

import json

from specfcg.scoring.scorecard import (
    DIMENSIONS,
    app_score,
    control,
    load_history,
    record_point,
    scorecard,
)

ENTRY = {
    "app": "markor",
    "coverage": {"covered": 17, "functions": 17, "score": 1.0},
    "random": {"score_union": 0.4},
    "probes": {
        "probes": [{"function": "sort"}],
        "calibration": {"probes": 6, "predicted": 0.45, "actual": 0.5},
    },
    "selfopt": {
        "summary": {"covered_start": 6, "covered_end": 9, "total": 17},
    },
    "bench": [
        {
            "agent": "specfcg",
            "rows": [
                {"success": True},
                {"success": False},
            ],
        }
    ],
}


def test_each_dimension_is_a_percentage_traced_to_one_record():
    scores = app_score(ENTRY)

    assert scores == {
        "graph": 100.0,
        "calibration": 95.0,
        "selfopt": 17.6,
        "task": 50.0,
    }


def test_missing_records_score_zero_rather_than_raising():
    scores = app_score({"app": "empty"})

    assert scores == {key: 0.0 for key, _label, _source in DIMENSIONS}


def test_random_traversal_is_a_control_not_a_dimension():
    """Unguided reachability is a property of the app, not of the system.

    It is reported beside the score as the control the graph is compared
    against; giving it weight would move the score without measuring any
    capability.
    """
    entry = {**ENTRY}
    card = scorecard([entry])

    assert "random" not in card["dims"]
    assert card["control"]["random"] == 40.0
    assert card["overall"] == round(
        sum(card["dims"].values()) / len(DIMENSIONS), 1
    )


def test_scorecard_means_each_dimension_across_apps():
    card = scorecard([ENTRY, {**ENTRY, "app": "amaze", "coverage": {"score": 0.5}}])

    assert card["apps"] == {"markor": app_score(ENTRY), "amaze": app_score({**ENTRY, "coverage": {"score": 0.5}})}
    assert card["dims"]["graph"] == 75.0
    assert card["dims"]["task"] == 50.0
    assert card["overall"] == round(sum(card["dims"].values()) / len(DIMENSIONS), 1)


def test_recording_a_point_is_idempotent_for_the_same_label(tmp_path):
    path = tmp_path / "score-history.json"
    card = scorecard([ENTRY])

    first = record_point(path, "baseline", card)
    second = record_point(path, "baseline", card)

    assert first["iteration"] == 0
    assert second["iteration"] == 0
    assert len(load_history(path)) == 1


def test_recording_a_new_label_appends_the_next_iteration(tmp_path):
    path = tmp_path / "score-history.json"
    card = scorecard([ENTRY])

    record_point(path, "baseline", card)
    improved = scorecard([{**ENTRY, "coverage": {"score": 1.0}, "random": {"score_union": 0.5}}])
    point = record_point(path, "matcher-fix", improved)

    assert point["iteration"] == 1
    history = load_history(path)
    assert [entry["label"] for entry in history] == ["baseline", "matcher-fix"]
    assert history[-1]["overall"] == improved["overall"]
    assert json.loads(path.read_text(encoding="utf-8"))["points"][-1]["label"] == "matcher-fix"


def test_history_is_empty_before_the_first_recording(tmp_path):
    assert load_history(tmp_path / "missing.json") == []


def test_collect_entries_reads_the_run_directory_layout(tmp_path):
    """The scorecard owns the layout: experiments/, seed-experiments/, bench-*."""
    from specfcg.scoring.scorecard import collect_entries

    app = tmp_path / "omninotes"
    (app / "experiments").mkdir(parents=True)
    (app / "seed-experiments").mkdir(parents=True)
    (app / "bench-specfcg").mkdir(parents=True)
    (app / "experiments" / "coverage.json").write_text(
        '{"covered": 23, "functions": 23, "score": 1.0}', encoding="utf-8"
    )
    (app / "seed-experiments" / "probes.json").write_text(
        '{"probes": [{"function": "create_checklist"}],'
        ' "calibration": {"probes": 1, "predicted": 0.4, "actual": 0.5}}',
        encoding="utf-8",
    )
    (app / "seed-experiments" / "selfopt.json").write_text(
        '{"summary": {"covered_start": 6, "covered_end": 9, "total": 23}}',
        encoding="utf-8",
    )
    (app / "bench-specfcg" / "summary.json").write_text(
        '{"agent": "specfcg", "rows": [{"success": true}]}', encoding="utf-8"
    )

    entries = collect_entries(tmp_path)

    assert [entry["app"] for entry in entries] == ["omninotes"]
    entry = entries[0]
    assert entry["coverage"]["covered"] == 23
    assert entry["probes"]["calibration"]["predicted"] == 0.4
    assert entry["bench"][0]["agent"] == "specfcg"
    assert app_score(entry)["graph"] == 100.0


def test_a_zero_round_selfopt_record_never_outscores_a_measured_one(tmp_path):
    """The self-optimization dimension measures growth from an incomplete graph.

    Re-running the growth experiment against the *complete* graph finds
    nothing uncovered, so it writes a zero-round record.  Read as a
    measurement that record says the system gained nothing, which is true
    of that run and false of the system: the growth it was meant to
    measure happened on the seed graph.  A run with no rounds is a
    non-measurement, so the recorded seed run stays the evidence for the
    dimension no matter which file is newer.
    """
    from specfcg.scoring.scorecard import collect_entries

    app = tmp_path / "amaze"
    (app / "experiments").mkdir(parents=True)
    (app / "seed-experiments").mkdir(parents=True)
    (app / "experiments" / "selfopt.json").write_text(
        '{"summary": {"rounds": 0, "covered_start": 0, "covered_end": 0,'
        ' "total": 20}}',
        encoding="utf-8",
    )
    (app / "seed-experiments" / "selfopt.json").write_text(
        '{"summary": {"rounds": 4, "covered_start": 7, "covered_end": 11,'
        ' "total": 20}}',
        encoding="utf-8",
    )

    entry = collect_entries(tmp_path)[0]

    assert entry["selfopt"]["summary"]["rounds"] == 4
    assert app_score(entry)["selfopt"] == 20.0


def test_a_probe_record_with_no_probes_does_not_replace_the_seed_run(tmp_path):
    """The probe experiment also runs on an incomplete graph.

    On a complete graph there is nothing left to probe, so the run saves an
    empty probe list.  That record is the same non-measurement as a
    zero-round growth run, and the recorded seed run stays the evidence.
    """
    from specfcg.scoring.scorecard import collect_entries

    app = tmp_path / "amaze"
    (app / "experiments").mkdir(parents=True)
    (app / "seed-experiments").mkdir(parents=True)
    (app / "experiments" / "probes.json").write_text(
        '{"probes": [], "calibration": {"probes": 0, "predicted": 0.0,'
        ' "actual": 0.0}}',
        encoding="utf-8",
    )
    (app / "seed-experiments" / "probes.json").write_text(
        '{"probes": [{"function": "rename"}], "calibration": {"probes": 1,'
        ' "predicted": 0.45, "actual": 0.5}}',
        encoding="utf-8",
    )

    entry = collect_entries(tmp_path)[0]

    assert entry["probes"]["calibration"]["probes"] == 1


def test_a_calibration_over_zero_probes_earns_no_score():
    """A perfect prediction of nothing is not a perfect prediction.

    With no probe the predicted and actual rates are both zero, so the
    dimension's 100 − |predicted − actual| formula returns 100 for a run
    that measured nothing at all.
    """
    entry = {
        **ENTRY,
        "probes": {
            "calibration": {
                "probes": 0,
                "predicted": 0.0,
                "actual": 0.0,
                "gap": 0.0,
            }
        },
    }

    assert app_score(entry)["calibration"] == 0.0


def test_measured_is_the_one_rule_the_readers_and_writers_share():
    """The experiment scripts and the scorecard must agree on what counts.

    A runner that saves a vacuous record and a scorecard that reads it as a
    score would disagree about the same file; one predicate answers both
    questions, so they cannot.
    """
    from specfcg.scoring.scorecard import measured

    assert measured({"summary": {"rounds": 0}}, "selfopt") is None
    assert measured({"summary": {"rounds": 3}}, "selfopt") is not None
    assert measured({"probes": []}, "probes") is None
    assert measured({"probes": [{"function": "sort"}]}, "probes") is not None
    assert measured(None, "probes") is None


def test_the_graph_dimension_is_recomputed_from_the_graph_not_read_back():
    """A stored coverage number is a snapshot of an older matcher.

    ``coverage.json`` holds what ``graph_coverage`` returned when the
    experiment ran.  When the matcher is corrected -- here, the inventory's
    ``cards`` hints stopped being scored -- every stored record becomes a
    number produced by a rule the code no longer has.  Scoring the snapshot
    would keep the old answer, so the scorecard asks the current rule, over
    the graph and the inventory it can read from disk.
    """
    from pathlib import Path

    import pytest

    from specfcg.scoring.scorecard import coverage_from_disk

    root = Path(__file__).resolve().parents[1]
    graph = root / "runs" / "mobileworld" / "activitydiary" / "graph"
    if not graph.exists():
        # `runs/` is git-ignored: the graph is a local artifact, and CI has
        # none.  The property under test is that the scorecard recomputes
        # from the graph on disk; with no graph on disk there is nothing to
        # recompute, and asserting a number would only assert this machine's
        # history.
        pytest.skip("no local graph under runs/ (git-ignored artifact)")

    report = coverage_from_disk("activitydiary", root / "runs" / "mobileworld")
    assert report is not None

    # The property is that the scorecard asks the current rule over the graph
    # and inventory on disk.  The exact numbers belong to whichever graph is
    # on this machine -- a rebuild changes them, and pinning them would mean
    # the test fails every time the graph is honestly rebuilt.
    from specfcg.scoring.coverage_eval import graph_coverage, load_inventory
    from specfcg.cards.store import CardStore
    from specfcg.graph.store import GraphStore

    inventory = load_inventory(root / "benchmark" / "coverage" / "activitydiary.yaml")
    fresh = graph_coverage(
        inventory,
        GraphStore(graph, CardStore(graph)).load(),
    )
    assert report.covered == fresh.covered
    assert report.total == fresh.total
    assert report.total > 0


def test_a_record_from_the_graph_arm_counts_under_either_name():
    """The arm was renamed; records keep the name they were written with."""
    old = {"bench": [{"agent": "specfcg", "rows": [{"success": True}]}]}
    new = {"bench": [{"agent": "graph", "rows": [{"success": True}]}]}
    assert app_score(old)["task"] == app_score(new)["task"]


def test_the_task_dimension_reads_the_graph_arm_only():
    """The raw arm is a control: its success is the agent's competence.

    Folding it into the score would credit the graph with work the agent did
    without it; the graph's contribution is the paired difference.
    """
    entry = {
        "bench": [
            {"agent": "graph", "rows": [{"success": True}, {"success": False}]},
            {"agent": "raw", "rows": [{"success": True}, {"success": True}]},
        ]
    }
    assert app_score(entry)["task"] == 50.0
    assert control([entry])["raw"] == 100.0


def test_both_controls_are_reported_beside_the_score():
    entry = {
        "random": {"score_union": 0.4},
        "bench": [{"agent": "raw", "rows": [{"success": True}]}],
    }
    result = control([entry])
    assert result == {"random": 40.0, "raw": 100.0}

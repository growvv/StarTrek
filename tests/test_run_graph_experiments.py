from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "run_graph_experiments",
        ROOT / "scripts" / "run_graph_experiments.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_probe_run_with_nothing_to_probe_saves_no_record(tmp_path):
    """Pointing the probe experiment at a complete graph measures nothing.

    With every function covered there is no probe to run, so the record
    holds an empty list.  Written to the complete-graph slot it replaces the
    seed run's real calibration with a perfect prediction of nothing -- the
    scorecard's 100 − |predicted − actual| formula reads two zeros as a
    perfect estimate.  A run that probed nothing is not a measurement.
    """
    module = _module()
    out = tmp_path / "experiments"
    out.mkdir()

    module.save_probes(out, {"app": "amaze", "probes": [], "calibration": {}})

    assert not (out / "probes.json").exists()
    assert not (out / "latest.json").exists()


def test_a_probe_run_with_probes_saves_its_record(tmp_path):
    module = _module()
    out = tmp_path / "experiments"
    out.mkdir()
    payload = {
        "app": "amaze",
        "probes": [{"function": "rename"}],
        "calibration": {"probes": 1, "predicted": 0.45, "actual": 0.0},
    }

    module.save_probes(out, payload)

    assert (out / "probes.json").exists()
    assert (out / "latest.json").exists()

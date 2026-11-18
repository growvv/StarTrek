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


class _RecordingPipeline:
    """A pipeline whose plan_path and executor record how they were called."""

    def __init__(self):
        self.plan_calls: list[tuple[str, list[str], str]] = []
        self.execute_calls: list[tuple[object, int]] = []
        self.observed: list[str] = []
        self.executor = self
        # The probe path resets and launches the app through the pipeline's
        # script-facing device; a fake keeps the test off a real phone.
        self.device = type(
            "D",
            (),
            {"set_app": lambda self, package: None},
        )()

    def observe(self, package: str) -> str:
        self.observed.append(package)
        return "notes list"

    def plan_path(self, goal, path, state="", app=""):
        self.plan_calls.append((goal, list(path), app))
        from specfcg.models import Goal, TestPlan

        return TestPlan(goal=Goal(goal, app=app), path=list(path), app=app)

    def execute(self, plan, max_steps=None):
        from specfcg.models import RunResult

        self.execute_calls.append((plan, max_steps))
        return RunResult(plan=plan, success=True, goal_success=True, step_results=[])


def test_the_probe_plan_carries_the_app_package(tmp_path):
    """A probe executes through the agent, and the agent needs the package.

    Without it the plan's app is empty and the agent runs against whatever
    package happens to be current — which, after `fresh_app`, is not
    necessarily the app the probe is about.
    """
    module = _module()
    pipeline = _RecordingPipeline()
    from specfcg.benchmark.coverage_eval import FunctionSpec

    function = FunctionSpec(
        id="rename",
        label="rename",
        cards=[],
        ui_evidence=[],
        reachable=True,
    )

    module.run_probes(
        app="amaze",
        package="com.amaze.filemanager",
        functions=[function],
        graph=type("G", (), {"cards": {}, "edges": []})(),
        serial="emulator-5600",
        out_dir=tmp_path,
        limit=1,
        steps=3,
        pipeline=pipeline,
    )

    assert pipeline.plan_calls, "the probe should have planned a path"
    assert pipeline.plan_calls[0][2] == "com.amaze.filemanager"
    assert pipeline.execute_calls, "the probe should have executed through the executor"

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


class _FakeOps:
    """The device bridge, recording instead of shelling out to adb."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def clear_app(self, package: str) -> None:
        self.calls.append(("clear_app", package))

    def launch(self, package: str) -> None:
        self.calls.append(("launch", package))

    def act(self, action: str, target: str, args: str = "") -> bool:
        self.calls.append((action, target))
        return True


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
    from specfcg.scoring.coverage_eval import FunctionSpec

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
        # Injected: CI has no adb, and the probe's planning and execution are
        # what this test is about, not the device bridge.
        ops=_FakeOps(),
    )

    assert pipeline.plan_calls, "the probe should have planned a path"
    assert pipeline.plan_calls[0][2] == "com.amaze.filemanager"
    assert pipeline.execute_calls, "the probe should have executed through the executor"


def test_the_graph_arm_uses_the_serial_it_was_given(monkeypatch, tmp_path):
    """Four emulators run in parallel; each pipeline must act on its own.

    The config carries one machine's default serial.  When the graph arm
    ignored `--serial`, its pipeline observed whichever app happened to be in
    the foreground on that other emulator, so every card looked inexecutable
    and the arm scored zero for a reason that had nothing to do with the graph.
    """
    import scripts.run_mobileworld_bench as bench

    seen: dict[str, str] = {}

    class _Config:
        paths = type("P", (), {"root": ""})()
        device = type("D", (), {"serial": "emulator-5600"})()
        llm = type("L", (), {"base_url": "", "api_key_env": "X"})()
        agent = type("A", (), {"model": "m", "fallback_model": "m"})

    monkeypatch.setattr(bench, "load_config", lambda _path: _Config())

    def fake_build(config, **_kwargs):
        seen["serial"] = config.device.serial
        raise SystemExit("stop here: construction is what matters")

    monkeypatch.setattr(bench, "build_pipeline", fake_build)

    graph_root = tmp_path / "graph"
    (graph_root / "cards").mkdir(parents=True)
    try:
        bench.main([
            "--app", "amaze", "--agent", "graph", "--serial", "emulator-5604",
            "--graph-root", str(graph_root), "--out", str(tmp_path / "out"),
        ])
    except SystemExit:
        pass

    assert seen["serial"] == "emulator-5604"


def test_the_random_arm_takes_a_task_like_every_other_agent():
    """The runner calls every agent the same way: `agent(task)`.

    `RandomTraversalAgent` reads `task.max_steps`.  The traversal experiment
    still called it with `(goal, steps)`, which raised TypeError only on that
    path — the ablation and the traversal measurement disagreed about the
    callable's shape, and no unit test covered the experiment path.
    """
    import inspect

    from specfcg.benchmark.agents import RandomTraversalAgent

    params = list(inspect.signature(RandomTraversalAgent.__call__).parameters)
    assert params[:2] == ["self", "task"]

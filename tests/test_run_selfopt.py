from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "run_selfopt", ROOT / "scripts" / "run_selfopt.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolve_graph_root_defaults_to_the_app_graph():
    module = _module()
    assert module.resolve_graph_root("omninotes", "") == (
        ROOT / "runs" / "mobileworld" / "omninotes" / "graph"
    )


def test_resolve_graph_root_accepts_a_seed_graph():
    """The curve starts from a deliberately incomplete graph.

    Growing the completed graph would have nothing to add, so the run has to
    be able to point at the seed graph built from a subset of the traces.
    """
    module = _module()
    assert module.resolve_graph_root(
        "omninotes", "runs/mobileworld/omninotes/seed-graph"
    ) == ROOT / "runs" / "mobileworld" / "omninotes" / "seed-graph"


class _FakeDevice:
    def __init__(self, screen: str) -> None:
        self.screen = screen
        self.started: list[str] = []
        self.calls: list[tuple[str, str, str]] = []

    def start_app(self, package: str) -> None:
        self.started.append(package)

    def dump_ui(self) -> str:
        return self.screen

    def execute(self, action: str, target: str, args: str = "") -> bool:
        self.calls.append((action, target, args))
        return True


def test_a_round_starts_from_the_app_launch_state():
    """Every round is an independent measurement from a fresh launch.

    Rounds used to start from wherever the previous probe stopped.  The
    first "capability" a round then found was the one that undoes that
    probe -- relaunch the app, dismiss the dialog it opened -- so the curve
    counted recovery steps instead of the function each round targeted.
    The benchmark resets the app before every task; a measurement round has
    to do the same.
    """
    module = _module()
    device = _FakeDevice("home screen")

    state = module.launch_state(device, "com.example.notes", [])

    assert device.started == ["com.example.notes"]
    assert state == "home screen"


def test_a_round_replays_the_benchmarks_onboarding_steps():
    """The benchmark starts every task past the first-run screens.

    A fresh launch of an unvisited app lands on an onboarding pager or a
    permission dialog, not on the app's main screen.  The benchmark clicks
    through that before handing the task to an agent, so a round that skips
    it measures a screen no benchmark task ever starts from -- and the
    first card it discovers is a way out of onboarding.
    """
    module = _module()
    device = _FakeDevice("notes list")

    module.launch_state(
        device,
        "com.example.notes",
        [
            {"action": "click", "target": "resourceId=app:id/next"},
            {"action": "click", "target": "text=OK"},
        ],
    )

    assert device.started == ["com.example.notes"]
    assert device.calls == [
        ("click", "resourceId=app:id/next", ""),
        ("click", "text=OK", ""),
    ]


def test_an_experiment_runs_on_a_copy_of_its_graph(tmp_path):
    """The graph under test is a copy, never the recorded one.

    Self-optimization writes every discovered card back into the graph it
    reads.  Pointing a run at ``runs/.../seed-graph`` therefore made the
    experiment mutate its own baseline: the next run measured growth from
    the previous run's result, and the seed graph stopped being the fixed
    starting point the curve is supposed to be relative to.
    """
    module = _module()
    seed = tmp_path / "seed-graph"
    (seed / "cards").mkdir(parents=True)
    (seed / "cards" / "open_note.md").write_text("# open_note\n", "utf-8")

    work = module.working_graph(seed, tmp_path / "work")

    assert work != seed
    assert (work / "cards" / "open_note.md").exists()
    (work / "cards" / "new.md").write_text("# new\n", "utf-8")
    assert not (seed / "cards" / "new.md").exists()


def test_a_rerun_does_not_reuse_the_previous_working_graph(tmp_path):
    """A stale working copy would make the next run's start point its end."""
    module = _module()
    seed = tmp_path / "seed-graph"
    (seed / "cards").mkdir(parents=True)
    (seed / "cards" / "open_note.md").write_text("# open_note\n", "utf-8")
    work = tmp_path / "work"
    (work / "cards").mkdir(parents=True)
    (work / "cards" / "discovered_last_time.md").write_text("# x\n", "utf-8")

    fresh = module.working_graph(seed, work)

    assert fresh == work
    assert not (fresh / "cards" / "discovered_last_time.md").exists()
    assert (fresh / "cards" / "open_note.md").exists()


def test_a_run_with_nothing_to_grow_saves_no_record(tmp_path):
    """Pointing the growth experiment at a complete graph measures nothing.

    The run finds no uncovered function, so it executes zero rounds.  Its
    record would say the system gained nothing, replacing the seed run's
    real measurement with a zero; the file it was written to would also
    claim to describe a graph it never grew.  A run with no round is not a
    measurement, so it leaves the record alone.
    """
    module = _module()

    assert module.should_record({"rounds": 0}) is False
    assert module.should_record({"rounds": 3}) is True

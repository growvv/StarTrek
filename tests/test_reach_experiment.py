"""The reachability experiment measures the description, not the executor."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from specfcg.benchmark.reach_experiment import (
    ReachExperiment,
    ReachRun,
    paired_summary,
    task_text,
    target_for_version,
)
from specfcg.benchmark.reachability import TARGET_BY_CLASS
from specfcg.benchmark.suite_runner import AgentRun


class FakeDevice:
    """A device whose final screen is set per arm."""

    def __init__(self, final_ui: str = "", package: str = "com.example.app") -> None:
        self.final_ui = final_ui
        self.package = package
        self.installed: list[str] = []
        self.launched: list[str] = []

    def install(self, apk) -> bool:
        self.installed.append(str(apk))
        return True

    def clear_app(self, package: str) -> None:
        pass

    def shell(self, command: str) -> str:
        if "dumpsys window" in command:
            # The app is in front after `launch`; the settler reads this.
            return f"mCurrentFocus=Window{{a u0 {self.package}/.Main}}"
        return ""

    def launch(self, package: str) -> None:
        self.launched.append(package)

    def ui_text(self) -> str:
        return self.final_ui

    def act(self, action: str, target: str) -> bool:
        return False


def _version(tmp_path: Path, crash_frame: str) -> SimpleNamespace:
    apk = tmp_path / "app.apk"
    apk.write_text("", encoding="utf-8")
    return SimpleNamespace(
        id="app-1.0-#1",
        app="app",
        package="com.example.app",
        crashes=[SimpleNamespace(frames=[crash_frame])],
    ), apk


def _agent(steps: int = 3):
    def run(task):
        return AgentRun(steps=[{"action": "tap"}] * steps, done=True)

    return run


def test_the_goal_does_not_name_the_control():
    """Naming it would hand the agent the graph's own job."""
    text = task_text(TARGET_BY_CLASS["FileInfoDialog"])

    assert "info dialog" in text
    assert "tap" not in text.lower()


def test_the_target_comes_from_the_crash_stack(tmp_path):
    version, apk = _version(
        tmp_path, "net.gsantner.markor.ui.FileInfoDialog.setUpDialog"
    )

    target = target_for_version(version)

    assert target is not None
    assert target.name == "file info dialog"


def test_a_reached_screen_is_recorded_from_the_final_ui(tmp_path):
    version, apk = _version(
        tmp_path, "net.gsantner.markor.ui.FileInfoDialog.setUpDialog"
    )
    device = FakeDevice("id='ui__fileinfodialog__description'")
    experiment = ReachExperiment(
        device, None, None, tmp_path / "runs", settle_s=0, after_s=0
    )

    run = experiment.run(
        version, target_for_version(version), "graph", _agent(), max_steps=5,
        apk=apk,
    )

    assert run.reached is True
    assert (tmp_path / "runs" / version.id / "graph" / "result.json").exists()


def test_not_reaching_is_also_a_record(tmp_path):
    version, apk = _version(
        tmp_path, "net.gsantner.markor.ui.FileInfoDialog.setUpDialog"
    )
    device = FakeDevice("TextView text='Notebook'")
    experiment = ReachExperiment(
        device, None, None, tmp_path / "runs", settle_s=0, after_s=0
    )

    run = experiment.run(
        version, target_for_version(version), "raw", _agent(), max_steps=5,
        apk=apk,
    )

    assert run.reached is False
    assert run.missing == ["fileinfodialog"]


def test_the_paired_summary_counts_only_targets_both_arms_ran():
    runs = [
        ReachRun(version="a", arm="graph", target="t", reached=True),
        ReachRun(version="a", arm="raw", target="t", reached=False),
        ReachRun(version="b", arm="graph", target="t", reached=False),
        ReachRun(version="b", arm="raw", target="t", reached=False),
        ReachRun(version="c", arm="graph", target="t", reached=True),
    ]

    summary = paired_summary(runs)

    assert summary["per_arm"]["graph"]["reached"] == 2
    assert summary["per_arm"]["raw"]["reached"] == 0
    # `c` has only one arm, so it is outside the paired comparison.
    assert summary["paired"]["shared"] == 2
    assert summary["paired"]["delta"] == 1


def test_a_failed_agent_call_is_a_datum_not_a_crash(tmp_path):
    version, apk = _version(
        tmp_path, "net.gsantner.markor.ui.FileInfoDialog.setUpDialog"
    )

    def broken(task):
        raise RuntimeError("model went away")

    experiment = ReachExperiment(
        FakeDevice(), None, None, tmp_path / "runs", settle_s=0, after_s=0
    )

    run = experiment.run(
        version, target_for_version(version), "graph", broken, max_steps=5,
        apk=apk,
    )

    assert run.reached is False
    assert "model went away" in run.error


def test_a_graph_that_cannot_plan_is_not_counted_as_a_failed_attempt(tmp_path):
    """A missing plan is the graph's failure, not the agent's.

    Both read `steps=0, reached=False` without the flag, so the comparison
    would count a plan the graph never produced against the agent.
    """
    version, apk = _version(
        tmp_path, "net.gsantner.markor.ui.FileInfoDialog.setUpDialog"
    )

    def no_plan(task):
        return AgentRun(steps=[], no_plan=True)

    experiment = ReachExperiment(
        FakeDevice(), None, None, tmp_path / "runs", settle_s=0, after_s=0
    )
    run = experiment.run(
        version, target_for_version(version), "graph", no_plan, max_steps=5,
        apk=apk,
    )

    assert run.no_plan is True
    assert run.reached is False


def test_an_unknown_data_path_is_a_note_not_an_error(tmp_path):
    """A build with no known seed path can still have tasks that need no file."""
    version, apk = _version(
        tmp_path, "net.gsantner.markor.ui.FileInfoDialog.setUpDialog"
    )
    version.package = "com.example.unknown"
    experiment = ReachExperiment(
        FakeDevice(package="com.example.unknown"), None, None,
        tmp_path / "runs", settle_s=0, after_s=0,
    )

    run = experiment.run(
        version, target_for_version(version), "raw", _agent(), max_steps=5,
        apk=apk,
    )

    assert run.seed_note.startswith("no known data path")
    assert run.error == ""

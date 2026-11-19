"""Run the reachability experiment: graph description vs the raw goal.

Both arms use the same agent, the same device and the same build.  The only
difference is the text the agent is given.  The oracle is the final UI dump:
did the screen the crash happens on appear?

That makes this experiment answerable in a way the crash experiment is not.
The crash experiment needs the agent to finish the walk *and* land on the
exact state that crashes, so when the executor is weak both arms read zero
and the difference says nothing.  Here a run that gets to the dialog is a
success whether or not the bug fires, so the measurement sits where the
method's claim does: the description's job is to get the agent to the right
screen.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from specfcg.benchmark.reachability import (
    ReachResult,
    TargetScreen,
    reached,
    target_for,
    summarise,
)


@dataclass
class ReachRun:
    """One arm's attempt at one target."""

    version: str
    arm: str
    target: str
    task_text: str = ""
    steps: int = 0
    reached: bool = False
    markers_seen: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    error: str = ""

    def as_record(self) -> dict:
        return {
            "version": self.version,
            "arm": self.arm,
            "target": self.target,
            "task": self.task_text,
            "steps": self.steps,
            "reached": self.reached,
            "markers_seen": self.markers_seen,
            "missing": self.missing,
            "error": self.error,
        }


def task_text(target: TargetScreen) -> str:
    """The goal both arms are given, phrased without naming any control.

    Naming a control would hand the agent the graph's job: the graph's claim
    is that its description says *how* to get there, and the control name is
    part of that how.
    """
    return f"In the app, {target.action} and leave the result visible on screen."


def target_for_version(version) -> TargetScreen | None:
    """The screen this build's crash happens on, from its stack."""
    for crash in version.crashes:
        target = target_for(crash.frames)
        if target is not None:
            return target
    return None


class ReachExperiment:
    """One build, one target, both arms."""

    def __init__(
        self,
        device,
        graph_arm,
        raw_arm,
        out_root: Path,
        settle_s: float = 3.0,
        after_s: float = 1.5,
    ) -> None:
        self.device = device
        self.graph_arm = graph_arm
        self.raw_arm = raw_arm
        self.out_root = Path(out_root)
        self.settle_s = settle_s
        self.after_s = after_s

    def _prepare(self, version, apk: Path) -> str:
        """Install the exact build and put it in a state a task can start from."""
        from specfcg.benchmark.first_run import (
            grant_storage_access,
            settle_first_run,
        )
        from specfcg.benchmark.seeding import prepare as seed_data

        if not self.device.install(apk):
            return f"could not install {apk}"
        self.device.clear_app(version.package)
        grant_storage_access(self.device, version.package)
        note = seed_data(self.device, version.package)
        self.device.launch(version.package)
        time.sleep(self.settle_s)
        launch = settle_first_run(
            self.device, version.package, settle_s=self.settle_s
        )
        if not launch.ready:
            return f"never reached the app: stuck on {launch.stuck_on}"
        return note

    def run(
        self,
        version,
        target: TargetScreen,
        arm: str,
        agent,
        max_steps: int,
        apk: Path | None = None,
    ) -> ReachRun:
        out = self.out_root / version.id / arm
        out.mkdir(parents=True, exist_ok=True)
        result = ReachRun(
            version=version.id, arm=arm, target=target.name
        )
        result.task_text = task_text(target)
        setup_note = self._prepare(version, apk) if apk is not None else ""
        if setup_note:
            result.error = setup_note

        from specfcg.benchmark.suite import BenchTask

        task = BenchTask(
            id=f"{version.id}-{arm}",
            app=version.app,
            package=version.package,
            template=result.task_text,
            max_steps=max_steps,
        )
        try:
            run = agent(task)
        except Exception as exc:  # noqa: BLE001 -- a failed run is a datum
            result.error = f"{type(exc).__name__}: {exc}"
            (out / "result.json").write_text(
                json.dumps(result.as_record(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return result

        result.steps = len(run.steps)
        if run.error and not result.error:
            result.error = run.error
        time.sleep(self.after_s)
        # `AdbOps` exposes the raw dump as `dump_ui`; the agent's wrapper adds
        # a compact `ui_text`.  The markers are widget ids, which both carry.
        if hasattr(self.device, "ui_text"):
            final_ui = self.device.ui_text()
        else:
            final_ui = self.device.dump_ui()
        (out / "final_ui.txt").write_text(final_ui, encoding="utf-8")
        check: ReachResult = reached(final_ui, target)
        result.reached = check.reached
        result.markers_seen = check.markers_seen
        result.missing = check.missing
        (out / "result.json").write_text(
            json.dumps(result.as_record(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return result


def paired_summary(runs: list[ReachRun]) -> dict:
    """Reach rate per arm, and the paired difference over shared targets."""
    by_arm: dict[str, dict[str, bool]] = {}
    for run in runs:
        by_arm.setdefault(run.arm, {})[run.version] = run.reached
    arms = sorted(by_arm)
    per_arm = {
        arm: summarise([
            ReachResult(version=v, target="", reached=hit)
            for v, hit in hits.items()
        ])
        for arm, hits in by_arm.items()
    }
    paired = {}
    if len(arms) == 2:
        left, right = arms
        shared = set(by_arm[left]) & set(by_arm[right])
        only_left = [v for v in shared if by_arm[left][v] and not by_arm[right][v]]
        only_right = [v for v in shared if by_arm[right][v] and not by_arm[left][v]]
        paired = {
            "shared": len(shared),
            f"{left}_only": sorted(only_left),
            f"{right}_only": sorted(only_right),
            "delta": len(only_left) - len(only_right),
        }
    return {"per_arm": per_arm, "paired": paired}

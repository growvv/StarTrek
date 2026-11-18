"""Run one buggy build and ask whether the known crash happened.

The comparison this experiment makes is the paper's: the same agent, the same
device, the same task text, against a build with a recorded crash.  A run
counts as a detection only when the app's own process dies with the recorded
exception at the recorded place — never when the agent reports success, and
never when a neighbouring process crashes.

Nothing here decides what to do with the app.  It installs, clears logcat,
hands the task over, reads the log back, and returns what it saw.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from specfcg.benchmark.themis import BuggyVersion, crash_hit

# A crash that names the app's own process; the same shape FuncDroid checks.
_CRASH_RE = re.compile(
    r"FATAL EXCEPTION.*\n(?:.*\n){0,3}?.*Process:\s*(?P<package>[A-Za-z0-9_.]+)"
)


@dataclass
class BugRun:
    """What one build's run did, and whether it reached the recorded bug."""

    version_id: str
    app: str
    package: str
    task: str
    installed: bool = False
    steps: int = 0
    detected: bool = False
    error: str = ""
    logcat_path: str = ""
    matched_crash: str = ""


class BugExperiment:
    """Install a build, run a task against it, and read the crash log.

    The device is anything with `shell`, `install`, `uninstall`, `launch` and
    `clear_app` — the same shape the benchmark already uses, so a fake can
    drive the whole path in a test.
    """

    def __init__(
        self,
        device,
        agent,
        out_root: Path,
        settle_s: float = 3.0,
        after_s: float = 1.5,
    ) -> None:
        self.device = device
        self.agent = agent
        self.out_root = Path(out_root)
        # Waits the device needs, injectable so a test does not sleep them.
        self.settle_s = settle_s
        self.after_s = after_s

    def _install(self, apk: Path, version: BuggyVersion) -> bool:
        # A downgrade is refused by the package manager, and the dataset's
        # builds are older than whatever is on the device, so the old copy
        # has to go first.
        self.device.uninstall(version.package)
        return bool(self.device.install(apk))

    def run(self, version: BuggyVersion, apk: Path, task: str, max_steps: int = 25) -> BugRun:
        out = self.out_root / version.id
        out.mkdir(parents=True, exist_ok=True)
        result = BugRun(
            version_id=version.id,
            app=version.app,
            package=version.package,
            task=task,
        )
        result.installed = self._install(apk, version)
        if not result.installed:
            result.error = "install failed"
            return result

        self.device.shell("logcat -c")
        self.device.clear_app(version.package)
        self.device.launch(version.package)
        time.sleep(self.settle_s)

        try:
            trace = self.agent.run(task, max_steps, app=version.package)
        except Exception as exc:  # the caller wants a record, not a crash
            result.error = repr(exc)
            trace = None
        if trace is not None:
            result.steps = len(trace.steps)
            if trace.error:
                result.error = trace.error

        # Give the app a moment to die after the last action, then read back
        # everything the run produced.
        time.sleep(self.after_s)
        logcat = self.device.shell("logcat -d -v threadtime")
        log_path = out / "logcat.txt"
        log_path.write_text(logcat, encoding="utf-8", errors="replace")
        result.logcat_path = str(log_path)

        if crash_hit(logcat, version):
            result.detected = True
            result.matched_crash = _describe_match(logcat, version)
        return result


def _describe_match(logcat: str, version: BuggyVersion) -> str:
    """The line that made the match, for the report to quote."""
    for line in logcat.splitlines():
        if "FATAL EXCEPTION" in line:
            return line.strip()[:200]
    return ""


def summarise(runs: list[BugRun]) -> dict:
    """Detection counts, and the failures, side by side."""
    detected = [run for run in runs if run.detected]
    return {
        "versions": len(runs),
        "installed": sum(1 for run in runs if run.installed),
        "detected": len(detected),
        "detected_ids": [run.version_id for run in detected],
        "errors": {
            run.version_id: run.error
            for run in runs
            if run.error and not run.detected
        },
    }

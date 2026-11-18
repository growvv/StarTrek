"""A buggy build's run is judged by its own crash log, never by the agent."""
from __future__ import annotations

from pathlib import Path

import pytest

from specfcg.benchmark.bug_experiment import BugExperiment, summarise
from specfcg.benchmark.themis import BuggyVersion, CrashSignature
from specfcg.executor.agent import AgentTrace
from specfcg.models import Step

CRASH = """01-08 10:16:01.640 23018 23018 E AndroidRuntime: FATAL EXCEPTION: main
01-08 10:16:01.640 23018 23018 E AndroidRuntime: Process: com.example.app, PID: 23018
01-08 10:16:01.640 23018 23018 E AndroidRuntime: java.lang.NullPointerException: boom
01-08 10:16:01.640 23018 23018 E AndroidRuntime: \tat com.example.app.Foo.bar(Foo.java:42)
"""

VERSION = BuggyVersion(
    app="com.example.app",
    directory="Example-1.0-#1",
    package="com.example.app",
    version_code=1,
    version_name="1.0",
    crashes=[
        CrashSignature(
            exception="java.lang.NullPointerException",
            frames=["com.example.app.Foo.bar(Foo.java:42)"],
            process="com.example.app",
        )
    ],
)


class FakeDevice:
    def __init__(self, logcat: str = "", install_ok: bool = True) -> None:
        self.logcat = logcat
        self.install_ok = install_ok
        self.calls: list[str] = []
        self.uninstalled: list[str] = []

    def install(self, apk) -> bool:
        self.calls.append("install")
        return self.install_ok

    def uninstall(self, package: str) -> None:
        self.uninstalled.append(package)

    def shell(self, command: str) -> str:
        self.calls.append(command)
        if command.startswith("logcat -d"):
            return self.logcat
        return ""

    def clear_app(self, package: str) -> None:
        self.calls.append("clear")

    def launch(self, package: str) -> None:
        self.calls.append("launch")


class FakeAgent:
    def __init__(self, steps: int = 3, error: str = "") -> None:
        self.steps = steps
        self.error = error
        self.calls: list[tuple[str, int, str]] = []

    def run(self, task: str, max_steps: int, *, app: str) -> AgentTrace:
        self.calls.append((task, max_steps, app))
        return AgentTrace(
            steps=[Step(action="click", target="x") for _ in range(self.steps)],
            error=self.error,
        )


def _apk(tmp_path: Path) -> Path:
    path = tmp_path / "app.apk"
    path.write_bytes(b"apk")
    return path


def test_the_recorded_crash_counts_as_a_detection(tmp_path):
    device = FakeDevice(logcat=CRASH)
    run = BugExperiment(device, FakeAgent(), tmp_path, settle_s=0, after_s=0).run(
        VERSION, _apk(tmp_path), "do the thing"
    )

    assert run.detected is True
    assert run.installed is True
    assert "FATAL EXCEPTION" in run.matched_crash


def test_the_agent_reporting_success_does_not_make_a_detection(tmp_path):
    """The verdict is the crash log, not the agent's own claim."""
    device = FakeDevice(logcat="nothing crashed")
    run = BugExperiment(device, FakeAgent(), tmp_path, settle_s=0, after_s=0).run(
        VERSION, _apk(tmp_path), "do the thing"
    )

    assert run.detected is False
    assert run.steps == 3


def test_the_old_build_is_uninstalled_before_installing(tmp_path):
    """The dataset's builds are older than what is on the device.

    Without the uninstall the package manager refuses the downgrade and the
    run silently measures nothing.
    """
    device = FakeDevice(logcat=CRASH)
    BugExperiment(device, FakeAgent(), tmp_path, settle_s=0, after_s=0).run(
        VERSION, _apk(tmp_path), "task"
    )

    assert device.uninstalled == ["com.example.app"]


def test_a_failed_install_is_reported_not_run(tmp_path):
    device = FakeDevice(logcat=CRASH, install_ok=False)
    agent = FakeAgent()

    run = BugExperiment(device, agent, tmp_path).run(
        VERSION, _apk(tmp_path), "task"
    )

    assert run.installed is False
    assert run.detected is False
    assert agent.calls == []


def test_the_logcat_is_cleared_before_the_task(tmp_path):
    """A crash left by the previous build would be attributed to this one."""
    device = FakeDevice(logcat=CRASH)
    BugExperiment(device, FakeAgent(), tmp_path, settle_s=0, after_s=0).run(
        VERSION, _apk(tmp_path), "task"
    )

    assert device.calls.index("logcat -c") < device.calls.index("launch")


def test_the_task_and_the_package_reach_the_agent(tmp_path):
    agent = FakeAgent()
    BugExperiment(FakeDevice(logcat=CRASH), agent, tmp_path, settle_s=0, after_s=0).run(
        VERSION, _apk(tmp_path), "open settings", max_steps=9
    )

    assert agent.calls == [("open settings", 9, "com.example.app")]


def test_an_agent_error_is_recorded_without_losing_the_crash_check(tmp_path):
    device = FakeDevice(logcat=CRASH)
    run = BugExperiment(device, FakeAgent(error="adb died"), tmp_path).run(
        VERSION, _apk(tmp_path), "task"
    )

    assert run.error == "adb died"
    assert run.detected is True


def test_the_logcat_is_written_beside_the_run(tmp_path):
    run = BugExperiment(FakeDevice(logcat=CRASH), FakeAgent(), tmp_path, settle_s=0, after_s=0).run(
        VERSION, _apk(tmp_path), "task"
    )

    assert Path(run.logcat_path).exists()
    assert "FATAL EXCEPTION" in Path(run.logcat_path).read_text()


def test_the_summary_counts_detections_and_keeps_the_errors(tmp_path):
    ok = BugExperiment(FakeDevice(logcat=CRASH), FakeAgent(), tmp_path, settle_s=0, after_s=0).run(
        VERSION, _apk(tmp_path), "task"
    )
    failed = BugExperiment(
        FakeDevice(logcat="", install_ok=False), FakeAgent(), tmp_path,
        settle_s=0, after_s=0,
    ).run(VERSION, _apk(tmp_path), "task")

    summary = summarise([ok, failed])

    assert summary["versions"] == 2
    assert summary["installed"] == 1
    assert summary["detected"] == 1
    assert summary["detected_ids"] == [VERSION.id]
    assert VERSION.id in summary["errors"]

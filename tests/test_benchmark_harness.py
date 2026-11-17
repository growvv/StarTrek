from __future__ import annotations

from specfcg.benchmark.harness import (
    collect_final_state,
    prepare_state,
)


class FakeOps:
    """Records shell operations and answers file reads from memory."""

    def __init__(self) -> None:
        self.shell_calls: list[str] = []
        self.written: dict[str, str] = {}
        self.existing: dict[str, str] = {}
        self.dirs: set[str] = set()
        self.ui_text = ""
        self.focused = ""
        self.taps: list[str] = []

    def shell(self, command: str) -> str:
        self.shell_calls.append(command)
        return ""

    def write_file(self, path: str, content: str) -> None:
        self.written[path] = content

    def remove(self, path: str) -> None:
        self.written.pop(path, None)
        self.existing.pop(path, None)
        self.dirs.discard(path)

    def read_file(self, path: str) -> str | None:
        if path in self.written:
            return self.written[path]
        return self.existing.get(path)

    def is_dir(self, path: str) -> bool:
        return path in self.dirs

    def dump_ui(self) -> str:
        return self.ui_text

    def focused_package(self) -> str:
        return self.focused

    def clear_app(self, package: str) -> None:
        self.shell_calls.append(f"pm clear {package}")

    def launch(self, package: str) -> None:
        self.shell_calls.append(f"launch {package}")

    def act(self, action: str, target: str, args: str = "") -> bool:
        self.taps.append(f"{action}:{target}")
        return True


def _task(init=None, oracle=None):
    from specfcg.benchmark.suite import BenchTask

    return BenchTask(
        id="t",
        app="markor",
        package="net.gsantner.markor",
        template="Do it.",
        params={},
        init=init or {},
        oracle=oracle or {"ui_all": ["Done"]},
    )


def test_prepare_state_seeds_and_removes_files():
    ops = FakeOps()
    task = _task(
        init={
            "clear_app": True,
            "seed_files": {"/sdcard/a.md": "hello"},
            "seed_dirs": ["/sdcard/dir"],
            "remove_paths": ["/sdcard/old.md"],
        }
    )
    prepare_state(ops, task)

    assert "pm clear net.gsantner.markor" in ops.shell_calls
    assert ops.written["/sdcard/a.md"] == "hello"
    assert "/sdcard/dir" in ops.dirs
    assert "/sdcard/old.md" not in ops.existing


def test_prepare_state_removes_a_seeded_file_again_when_listed_last():
    ops = FakeOps()
    task = _task(
        init={
            "seed_files": {"/sdcard/x.md": "x"},
            "remove_paths": ["/sdcard/x.md"],
        }
    )
    prepare_state(ops, task)
    assert ops.read_file("/sdcard/x.md") is None


def test_collect_final_state_reads_only_paths_the_oracle_mentions():
    ops = FakeOps()
    ops.ui_text = "Grocery list\nBuy milk"
    ops.focused = "it.feio.android.omninotes.foss/MainActivity"
    ops.existing["/sdcard/a.md"] = "alpha"
    ops.dirs.add("/sdcard/work")

    oracle = {
        "ui_all": ["Grocery list"],
        "fs_exists": ["/sdcard/a.md"],
        "fs_dir": ["/sdcard/work"],
        "fs_content": {"/sdcard/a.md": ["alpha"]},
    }
    state = collect_final_state(ops, oracle)

    assert "Grocery list" in state.ui_text
    assert state.focused_package.startswith("it.feio")
    assert state.files["/sdcard/a.md"] == "alpha"
    assert "/sdcard/work" in state.dirs


def test_collect_final_state_does_not_touch_unrelated_paths():
    ops = FakeOps()
    state = collect_final_state(ops, {"ui_all": ["Done"]})
    assert state.files == {}
    assert state.dirs == set()


def test_collect_final_state_survives_a_failing_read():
    class BrokenOps(FakeOps):
        def read_file(self, path: str) -> str | None:
            raise OSError("adb died")

        def is_dir(self, path: str) -> bool:
            raise OSError("adb died")

    ops = BrokenOps()
    state = collect_final_state(
        ops, {"fs_exists": ["/sdcard/a"], "fs_dir": ["/sdcard/d"]}
    )
    assert state.files["/sdcard/a"] is None
    assert "/sdcard/d" not in state.dirs

def test_prepare_state_replays_onboarding_before_the_agent_runs():
    ops = FakeOps()
    task = _task(init={"clear_app": True})
    task.onboarding = [
        {"action": "click", "target": "text=Next"},
        {"action": "click", "target": "text=Done"},
    ]
    prepare_state(ops, task)
    assert ops.taps == ["click:text=Next", "click:text=Done"]
    assert ops.shell_calls.index("pm clear net.gsantner.markor") == 0
    assert ops.shell_calls.index("launch net.gsantner.markor") < 2


def test_prepare_state_skips_onboarding_that_is_not_declared():
    ops = FakeOps()
    prepare_state(ops, _task(init={"clear_app": True}))
    assert ops.taps == []


def test_fresh_app_runs_onboarding_after_launching():
    """A random-traversal episode must start where the agent starts.

    The control condition gets the same initialised app: cleared, launched,
    and past the first-run screens.  Otherwise it measures the onboarding
    wizard instead of the app.
    """
    from specfcg.benchmark.harness import fresh_app

    ops = FakeOps()

    fresh_app(
        ops,
        "it.feio.android.omninotes.foss",
        [{"action": "click", "target": "text=下一步"}],
    )

    assert ops.shell_calls == [
        "pm clear it.feio.android.omninotes.foss",
        "launch it.feio.android.omninotes.foss",
    ]
    assert ops.taps == ["click:text=下一步"]

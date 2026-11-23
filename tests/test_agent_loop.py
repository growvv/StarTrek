"""The agent's run loop, driven end to end with fakes.

Nothing covered `MobileAgent.run` before this file. The 556-test suite
exercised the pieces around it — the device wrapper, the prompts, the
recorder — and never the loop that calls them, which is where the stall
detection, the done-refusal and the artefact layout actually live. A
refactor of that loop could have broken every run while the suite stayed
green.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mobile_agent.agent import MobileAgent, TaskSpec


class FakeDevice:
    """A device that shows a scripted screen and records what it was asked."""

    def __init__(self, screens: list[str] | None = None) -> None:
        self.screens = list(screens or ["TextView text='Home'"])
        self.index = 0
        self.taps: list[tuple] = []

    def _screen(self) -> str:
        return self.screens[min(self.index, len(self.screens) - 1)]

    def ui_text(self, max_chars: int = 5000) -> str:
        return self._screen()

    def screenshot(self, path: Path | None = None):
        if path is not None:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"jpg")
        return SimpleNamespace(width=720, height=1280)

    def activity(self) -> str:
        return "app.MainActivity"

    def tap(self, **kwargs):
        self.taps.append(kwargs)
        self.index += 1
        return True, "OK tapped"

    def long_press(self, **kwargs):
        self.taps.append(kwargs)
        return True, "OK long-pressed"

    def tap_xy(self, x, y):
        self.taps.append(("xy", x, y))
        return True, "OK tapped"

    def type_text(self, text):
        return True, f"OK typed {text}"

    def press(self, key):
        self.taps.append(("press", key))
        return True, f"OK pressed {key}"

    def swipe(self, direction):
        return True, "OK swiped"

    def wait(self, seconds):
        return True, "OK waited"


class FakeLLM:
    """A VLM whose replies are scripted per call."""

    def __init__(self, replies: list[SimpleNamespace]) -> None:
        self.replies = list(replies)
        self.calls = 0
        self.seconds = 0.0
        self.models = ["fake-model"]
        self.prompts: list[str] = []

    def chat(self, messages, **kwargs):
        self.prompts.append(str(messages))
        self.calls += 1
        if self.replies:
            return self.replies.pop(0)
        return SimpleNamespace(content="", tool_calls=[])


class FakeMemory:
    def retrieve(self, goal, app):
        return []

    def add(self, **kwargs):
        return None


def _tool(name: str, **arguments) -> SimpleNamespace:
    import json

    return SimpleNamespace(
        function=SimpleNamespace(
            name=name, arguments=json.dumps(arguments)
        )
    )


def _reply(*calls: SimpleNamespace, content: str = "") -> SimpleNamespace:
    return SimpleNamespace(content=content, tool_calls=list(calls))


def _agent(tmp_path: Path, device, llm) -> MobileAgent:
    return MobileAgent(
        device=device,
        llm=llm,
        memory=FakeMemory(),
        out_root=tmp_path,
        verify=False,  # the caller judges; no verification call in the loop
    )


def _task(**overrides) -> TaskSpec:
    fields = dict(
        id="t1", app="app", app_name="App", goal="Open settings",
        max_steps=5,
    )
    fields.update(overrides)
    return TaskSpec(**fields)


def test_a_run_that_taps_then_finishes_records_every_step(tmp_path):
    """The ordinary path: plan, act, act, done."""
    device = FakeDevice(["Home", "Settings", "Settings"])
    llm = FakeLLM([
        _reply(content="1. Open the menu, 2. Tap Settings"),
        _reply(_tool("tap", text="Menu")),
        _reply(_tool("tap", text="Settings")),
        _reply(_tool("done", summary="Settings is open")),
    ])

    result = _agent(tmp_path, device, llm).run(_task())

    assert result.steps == 3
    assert (tmp_path / "t1" / "steps.json").exists()
    assert (tmp_path / "t1" / "result.json").exists()
    assert (tmp_path / "t1" / "done_summary.txt").read_text() == "Settings is open"


def test_a_repeated_action_is_reported_as_a_stall(tmp_path):
    """Two identical actions on an unchanged screen is the signal to stop.

    Without it the agent burns its whole budget on one tap, which is what the
    Markor runs did.
    """
    device = FakeDevice(["Home"])  # the screen never changes
    llm = FakeLLM([_reply(content="plan")] + [
        _reply(_tool("tap", text="Menu")) for _ in range(6)
    ])

    result = _agent(tmp_path, device, llm).run(_task(max_steps=8))

    assert result.steps < 8


def test_done_is_refused_once_while_a_confirmation_is_open(tmp_path):
    """Amaze's delete reported success on the confirmation dialog.

    The first done is refused with a reason; the agent may insist on the next
    turn, so a dialog that is the goal cannot trap it.
    """
    dialog = (
        "TextView text='Delete items permanently?' "
        "id='com.amaze.filemanager:id/md_buttonDefaultPositive'"
    )
    device = FakeDevice(["Home", dialog, dialog])
    llm = FakeLLM([
        _reply(content="plan"),
        _reply(_tool("tap", description="Delete")),
        _reply(_tool("done", summary="deleted")),   # refused
        _reply(_tool("done", summary="deleted")),   # accepted
    ])

    result = _agent(tmp_path, device, llm).run(_task())

    steps = __import__("json").loads(
        (tmp_path / "t1" / "steps.json").read_text()
    )
    refused = [s for s in steps if s.get("result") == "refused: unconfirmed dialog"]
    assert refused, steps
    # The tap, the refused done, and the accepted one are all recorded.
    assert result.steps == 3


def test_a_device_error_is_recorded_rather_than_raised(tmp_path):
    """A broken run is a datum; the benchmark must not crash on it."""
    class BrokenDevice(FakeDevice):
        def screenshot(self, path=None):
            raise RuntimeError("device disconnected")

    agent = _agent(tmp_path, BrokenDevice(), FakeLLM([_reply(content="p")]))

    result = agent.run(_task())

    assert result.success is False
    assert "device disconnected" in result.error
    assert (tmp_path / "t1" / "result.json").exists()

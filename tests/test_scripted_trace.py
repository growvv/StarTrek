from specfcg.executor.device import FakeDevice
from specfcg.traces.scripted import run_actions


def test_run_actions_records_state_transitions():
    device = FakeDevice(
        ["home", "editor", "list"], [True, True]
    )

    trace = run_actions(
        device,
        [
            {"action": "click", "target": "text=+", "wait": 0},
            {
                "action": "input",
                "target": "text=Title",
                "args": "Trip",
                "wait": 0,
            },
        ],
        app="notes",
        trace_id="t1",
        goal="create a note",
    )

    assert trace.trace_id == "t1"
    assert trace.app == "notes"
    assert trace.goal == "create a note"
    assert trace.start_state == "home"
    assert [step.after_state for step in trace.steps] == ["editor", "list"]
    assert trace.steps[1].args == "Trip"
    assert all(step.success for step in trace.steps)


def test_run_actions_records_failed_action():
    device = FakeDevice(["home"], [False])

    trace = run_actions(
        device,
        [{"action": "click", "target": "text=Missing", "wait": 0}],
        app="notes",
        trace_id="t1",
    )

    assert trace.steps[0].success is False


def test_run_actions_ignores_invalid_wait():
    device = FakeDevice(["home", "next"], [True])

    trace = run_actions(
        device,
        [{"action": "click", "target": "text=Go", "wait": "bad"}],
        app="notes",
        trace_id="t1",
    )

    assert len(trace.steps) == 1

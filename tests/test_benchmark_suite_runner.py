from __future__ import annotations

from specfcg.benchmark.suite import BenchTask
from specfcg.benchmark.suite_runner import AgentRun, TaskRunner


class FakeOps:
    def __init__(self) -> None:
        self.ui_text = "Done"
        self.focused = "it.feio.android.omninotes.foss/MainActivity"
        self.calls: list[str] = []

    def shell(self, command: str) -> str:
        self.calls.append(command)
        return ""

    def write_file(self, path: str, content: str) -> None:
        self.calls.append(f"write {path}")

    def remove(self, path: str) -> None:
        self.calls.append(f"rm {path}")

    def read_file(self, path: str) -> str | None:
        return None

    def is_dir(self, path: str) -> bool:
        return False

    def dump_ui(self) -> str:
        return self.ui_text

    def focused_package(self) -> str:
        return self.focused

    def clear_app(self, package: str) -> None:
        self.calls.append(f"pm clear {package}")

    def launch(self, package: str) -> None:
        self.calls.append(f"launch {package}")


def _task(**overrides) -> BenchTask:
    base = dict(
        id="t1",
        app="omninotes",
        package="it.feio.android.omninotes.foss",
        template="Create a note titled {title}.",
        params={"title": "Grocery list"},
        oracle={"ui_all": ["Grocery list"]},
        max_steps=20,
    )
    base.update(overrides)
    return BenchTask(**base)


def test_successful_task_records_steps_and_oracle_evidence():
    ops = FakeOps()
    ops.ui_text = "Grocery list\nNotes"
    runner = TaskRunner(ops, settle_s=0.0)

    def agent(task) -> AgentRun:
        assert task.goal == "Create a note titled Grocery list."
        return AgentRun(
            steps=[
                {"action": "click", "target": "fab", "args": "", "ok": True},
                {"action": "input", "target": "title", "args": "Grocery list", "ok": True},
            ],
            done=True,
        )

    outcome = runner.run(_task(), agent)

    assert outcome.success is True
    assert outcome.failure_type is None
    assert outcome.steps == 2
    assert outcome.max_steps == 20
    assert "PASS ui_all" in outcome.oracle_evidence
    assert outcome.reason == "all oracle checks passed"


def test_step_limit_is_a_failure_not_a_silent_stop():
    ops = FakeOps()
    ops.ui_text = "Notes"
    runner = TaskRunner(ops, settle_s=0.0)
    steps = [
        {"action": "click", "target": f"row{i}", "args": "", "ok": True}
        for i in range(20)
    ]

    outcome = runner.run(_task(), lambda task: AgentRun(steps=steps))

    assert outcome.success is False
    assert outcome.failure_type == "step_limit"
    assert outcome.steps == 20


def test_loop_is_detected_and_labelled():
    ops = FakeOps()
    ops.ui_text = "Notes"
    runner = TaskRunner(ops, settle_s=0.0)
    steps = [
        {"action": "click", "target": "menu", "args": "", "ok": True}
        for _ in range(6)
    ]

    outcome = runner.run(_task(), lambda task: AgentRun(steps=steps))

    assert outcome.failure_type == "loop_detected"
    assert "menu" in outcome.reason


def test_action_failure_is_labelled():
    ops = FakeOps()
    ops.ui_text = "Notes"
    runner = TaskRunner(ops, settle_s=0.0)

    def agent(task) -> AgentRun:
        return AgentRun(
            steps=[{"action": "click", "target": "x", "args": "", "ok": False}]
        )

    outcome = runner.run(_task(), agent)
    assert outcome.failure_type == "action_failure"


def test_no_plan_is_labelled():
    ops = FakeOps()
    ops.ui_text = "Notes"
    runner = TaskRunner(ops, settle_s=0.0)
    outcome = runner.run(
        _task(), lambda task: AgentRun(steps=[], no_plan=True)
    )
    assert outcome.failure_type == "no_plan"


def test_oracle_failure_is_the_default_for_a_completed_but_wrong_run():
    ops = FakeOps()
    ops.ui_text = "Notes"
    runner = TaskRunner(ops, settle_s=0.0)
    outcome = runner.run(
        _task(),
        lambda task: AgentRun(
            steps=[{"action": "click", "target": "x", "args": "", "ok": True}],
            done=True,
        ),
    )
    assert outcome.failure_type == "goal_oracle_failure"
    assert "Grocery list" in outcome.reason


def test_timeout_from_the_agent_is_labelled():
    ops = FakeOps()
    ops.ui_text = "Notes"
    runner = TaskRunner(ops, settle_s=0.0)
    outcome = runner.run(
        _task(),
        lambda task: AgentRun(
            steps=[{"action": "back", "target": "", "args": "", "ok": True}],
            error="timeout after 180s",
        ),
    )
    assert outcome.failure_type == "timeout"


def test_agent_crash_is_labelled():
    ops = FakeOps()
    ops.ui_text = "Notes"
    runner = TaskRunner(ops, settle_s=0.0)
    outcome = runner.run(
        _task(),
        lambda task: AgentRun(
            steps=[{"action": "back", "target": "", "args": "", "ok": True}],
            error="Process crashed: java.lang.RuntimeException",
        ),
    )
    assert outcome.failure_type == "app_crash"


def test_init_error_is_labelled_and_agent_is_not_run():
    class BrokenOps(FakeOps):
        def clear_app(self, package: str) -> None:
            raise RuntimeError("device offline")

    calls: list[str] = []
    runner = TaskRunner(BrokenOps(), settle_s=0.0)
    outcome = runner.run(
        _task(init={"clear_app": True}),
        lambda task: calls.append(goal) or AgentRun(steps=[]),
    )
    assert outcome.failure_type == "init_failure"
    assert calls == []
    assert "device offline" in outcome.reason


def test_runner_writes_one_latest_record_per_task(tmp_path):
    ops = FakeOps()
    ops.ui_text = "Grocery list"
    runner = TaskRunner(ops, settle_s=0.0, out_dir=tmp_path)

    runner.run(_task(), lambda task: AgentRun(steps=[], done=True))
    first = (tmp_path / "tasks" / "t1.json").read_text(encoding="utf-8")
    ops.ui_text = "Notes"
    runner.run(_task(), lambda task: AgentRun(steps=[], done=True))
    second = (tmp_path / "tasks" / "t1.json").read_text(encoding="utf-8")

    assert first != second
    assert '"success": false' in second
    assert len(list((tmp_path / "tasks").glob("t1*.json"))) == 1

from specfcg.executor.device import FakeDevice
from specfcg.executor.executor import Executor
from specfcg.executor.summarizer import StateSummarizer


def _executor(device, llm, graph):
    return Executor(device, llm, StateSummarizer(llm), graph)


def test_execute_success_returns_goal_success(
    fake_device, fake_llm, sample_graph, sample_plan
):
    fake_device = FakeDevice(["start", "after1", "after2"], [True, True])
    fake_llm.responses = [
        "Current screen: start",
        {"satisfied": True, "reason": "ok"},
        {"achieved": True, "reason": "ok"},
    ]
    result = _executor(fake_device, fake_llm, sample_graph).execute(sample_plan)
    assert result.success and result.goal_success
    assert len(result.step_results) == 2


def test_execute_records_partial_trace_on_step_failure(
    fake_device, fake_llm, sample_graph, sample_plan
):
    fake_device = FakeDevice(["start", "after1"], [True, False])
    fake_llm.responses = ["Current screen: start"]
    result = _executor(fake_device, fake_llm, sample_graph).execute(sample_plan)
    assert not result.success
    assert result.failure_type == "widget_failure"
    assert result.new_trace is not None
    assert len(result.new_trace.steps) == 2


def test_execute_check_error_does_not_crash(
    fake_device, fake_llm, sample_graph, sample_plan
):
    fake_device = FakeDevice(["start", "after1", "after2"], [True, True])
    fake_llm.responses = ["Current screen: start", "not json", "not json"]
    result = _executor(fake_device, fake_llm, sample_graph).execute(sample_plan)
    assert result.failure_type == "check_error"


def test_execute_postcondition_failure(
    fake_device, fake_llm, sample_graph, sample_plan
):
    fake_device = FakeDevice(["start", "after1", "after2"], [True, True])
    fake_llm.responses = [
        "Current screen: start",
        {"satisfied": False, "reason": "no note"},
    ]
    result = _executor(fake_device, fake_llm, sample_graph).execute(sample_plan)
    assert result.failure_type == "postcondition_failure"
    assert not result.success


def test_execute_checks_each_repeated_card_occurrence(
    fake_device, fake_llm, sample_graph, sample_card
):
    from specfcg.models import Goal, PlanStep, TestPlan

    plan = TestPlan(
        goal=Goal("create two notes"),
        path=["create_note", "create_note"],
        steps=[
            PlanStep(
                card="create_note",
                action="click",
                target="text=New",
                instance=0,
            ),
            PlanStep(
                card="create_note",
                action="click",
                target="text=New",
                instance=1,
            ),
        ],
    )
    fake_device = FakeDevice(["start", "after1", "after2"], [True, True])
    fake_llm.responses = [
        "Current screen: start",
        {"satisfied": True, "reason": "first"},
        {"satisfied": True, "reason": "second"},
        {"achieved": True, "reason": "ok"},
    ]

    result = _executor(fake_device, fake_llm, sample_graph).execute(plan)

    assert result.success
    assert len(fake_llm.prompts) == 4


def test_checks_include_compiled_steps(
    fake_device, fake_llm, sample_graph, sample_plan
):
    fake_device = FakeDevice(["start", "after1", "after2"], [True, True])
    fake_llm.responses = [
        "Current screen: start",
        {"satisfied": True, "reason": "ok"},
        {"achieved": True, "reason": "ok"},
    ]
    _executor(fake_device, fake_llm, sample_graph).execute(sample_plan)

    assert "click text=+" in fake_llm.prompts[1]
    assert "input text=Title args=Trip" in fake_llm.prompts[2]


def test_execute_string_false_postcondition_is_failure(
    fake_device, fake_llm, sample_graph, sample_plan
):
    fake_device = FakeDevice(["start", "after1", "after2"], [True, True])
    fake_llm.responses = [
        "Current screen: start",
        {"satisfied": "false", "reason": "no note"},
    ]
    result = _executor(fake_device, fake_llm, sample_graph).execute(sample_plan)
    assert result.failure_type == "postcondition_failure"
    assert not result.success


def test_execute_string_false_goal_is_failure(
    fake_device, fake_llm, sample_graph, sample_plan
):
    fake_device = FakeDevice(["start", "after1", "after2"], [True, True])
    fake_llm.responses = [
        "Current screen: start",
        {"satisfied": True, "reason": "ok"},
        {"achieved": "false", "reason": "no shared note"},
    ]
    result = _executor(fake_device, fake_llm, sample_graph).execute(sample_plan)
    assert result.failure_type == "goal_failure"
    assert not result.goal_success


def test_execute_goal_failure(
    fake_device, fake_llm, sample_graph, sample_plan
):
    fake_device = FakeDevice(["start", "after1", "after2"], [True, True])
    fake_llm.responses = [
        "Current screen: start",
        {"satisfied": True, "reason": "ok"},
        {"achieved": False, "reason": "no shared note"},
    ]
    result = _executor(fake_device, fake_llm, sample_graph).execute(sample_plan)
    assert result.failure_type == "goal_failure"
    assert not result.success
    assert not result.goal_success

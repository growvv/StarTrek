import json

from specfcg.benchmark.cases import NLTestCase
from specfcg.benchmark.pilot import Pilot
from specfcg.models import Goal, PlanStep, RunResult, TestPlan


class _Device:
    def __init__(self, state: str = "Notes list") -> None:
        self.state = state

    def dump_ui(self) -> str:
        return self.state


class _LLM:
    def __init__(self, misses: int = 0) -> None:
        self.misses = misses


class _Executor:
    def __init__(
        self, result: RunResult, llm: _LLM, misses: int = 0
    ) -> None:
        self.result = result
        self.llm = llm
        self.misses = misses
        self.plans: list[TestPlan] = []

    def execute(self, plan: TestPlan) -> RunResult:
        self.plans.append(plan)
        self.llm.misses += self.misses
        return self.result


class _Pipeline:
    def __init__(
        self,
        plan,
        result: RunResult,
        misses: int = 0,
        plan_misses: int = 2,
        execute_misses: int = 1,
    ) -> None:
        self.plan_result = plan
        self.llm = _LLM(misses)
        self.plan_misses = plan_misses
        self.executor = _Executor(result, self.llm, execute_misses)
        self.device = _Device()
        self.plan_calls: list[tuple[str, str, str]] = []

    def plan(self, text: str, state: str = "", app: str = ""):
        self.plan_calls.append((text, state, app))
        self.llm.misses += self.plan_misses
        return self.plan_result


def _plan() -> TestPlan:
    return TestPlan(
        goal=Goal("create a note"),
        path=["create_note"],
        steps=[
            PlanStep(
                card="create_note",
                action="click",
                target="resourceId=app:id/fab",
            )
        ],
    )


def _result(success: bool, goal_success: bool) -> RunResult:
    return RunResult(
        plan=_plan(),
        success=success,
        goal_success=goal_success,
        step_results=[
            {"card": "create_note", "action": "click", "success": True},
            {"card": "create_note", "action": "input", "success": False},
        ],
    )


def test_pilot_resets_and_records_a_case():
    pipeline = _Pipeline(_plan(), _result(True, True), misses=3)
    resets: list[int] = []
    pilot = Pilot(pipeline, reset=lambda: resets.append(1))

    row = pilot.run_case(NLTestCase("c1", "OmniNotes", "create a note"))

    assert resets == [1]
    assert pipeline.plan_calls == [("create a note", "Notes list", "")]
    assert row.case_id == "c1"
    assert row.planned is True
    assert row.path == ["create_note"]
    assert row.steps == 2
    assert row.actions_ok == 1
    assert row.success is True
    assert row.goal_success is True
    assert row.llm_calls == 3


def test_pilot_records_unplanned_case():
    pipeline = _Pipeline(
        None,
        _result(False, False),
        misses=0,
        plan_misses=1,
        execute_misses=0,
    )
    pilot = Pilot(pipeline)

    row = pilot.run_case(NLTestCase("c2", "OmniNotes", "unknown goal"))

    assert row.planned is False
    assert row.success is False
    assert row.path == []
    assert row.steps == 0
    assert row.llm_calls == 1


def test_pilot_writes_case_detail_with_plan_and_steps(tmp_path):
    pipeline = _Pipeline(
        _plan(),
        _result(True, True),
        misses=0,
        plan_misses=0,
        execute_misses=0,
    )
    pilot = Pilot(pipeline, detail_dir=tmp_path / "details")

    pilot.run_case(NLTestCase("c1", "OmniNotes", "create a note"))

    detail = json.loads(
        (tmp_path / "details" / "c1.json").read_text(encoding="utf-8")
    )
    assert detail["plan"]["path"] == ["create_note"]
    assert detail["result"]["step_results"][0]["action"] == "click"


def test_pilot_writes_one_json_line_per_case(tmp_path):
    pipeline = _Pipeline(
        _plan(),
        _result(True, True),
        misses=0,
        plan_misses=2,
        execute_misses=0,
    )
    rows = Pilot(pipeline).run(
        [
            NLTestCase("c1", "OmniNotes", "create a note"),
            NLTestCase("c2", "OmniNotes", "create a note"),
        ]
    )
    out = tmp_path / "pilot.jsonl"

    Pilot.write_jsonl(rows, out)

    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["case_id"] == "c1"
    assert json.loads(lines[0])["llm_calls"] == 2
    assert json.loads(lines[1])["llm_calls"] == 2

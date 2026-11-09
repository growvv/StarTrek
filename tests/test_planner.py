from specfcg.models import Goal
from specfcg.planner.binding import ParamBinder
from specfcg.planner.compiler import StepCompiler
from specfcg.planner.planner import Planner
from specfcg.planner.retrieval import CardRetriever


def _planner(graph, llm):
    return Planner(
        graph,
        llm,
        CardRetriever(llm),
        ParamBinder(llm),
        StepCompiler(llm),
    )


def test_plan_finds_path_and_steps(fake_llm, sample_graph):
    fake_llm.responses = [
        {"can_execute": True},
        {"is_goal": False},
        {"can_execute": True},
        {"is_goal": True},
        {"bindings": {"title": "Trip"}},
        {"steps": [{"action": "click", "target": "text=+", "args": ""}]},
        {"bindings": {}},
        {"steps": [{"action": "click", "target": "text=Share", "args": ""}]},
    ]
    plan = _planner(sample_graph, fake_llm).plan(
        Goal("create and share a note"), "start"
    )
    assert plan is not None
    assert plan.path == ["create_note", "share_note"]
    assert len(plan.steps) == 2


def test_plan_returns_none_when_no_path(fake_llm, sample_graph):
    fake_llm.responses = [{"can_execute": False}, {"can_execute": False}]
    assert (
        _planner(sample_graph, fake_llm).plan(Goal("impossible"), "start")
        is None
    )

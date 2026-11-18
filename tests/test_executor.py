from specfcg.executor.executor import Executor
from specfcg.models import Goal, TestPlan
from tests.fakes import ScriptedAgent


def _llm(achieved: bool = True, fake_llm=None):
    fake_llm.responses = [{"achieved": achieved, "reason": "checked"}]
    return fake_llm


def _graph(sample_graph):
    return sample_graph


def _plan(description: str = "Overall goal: create a note") -> TestPlan:
    return TestPlan(
        goal=Goal("create a note", app="it.feio.android.omninotes.foss"),
        path=["create_note"],
        description=description,
        assertions=["create a note"],
        app="it.feio.android.omninotes.foss",
    )


def test_the_agent_receives_the_plan_description(fake_llm, sample_graph):
    from specfcg.models import Step

    agent = ScriptedAgent(steps=[Step(action="click", target="text=+")])
    plan = _plan()
    Executor(agent, _llm(True, fake_llm), sample_graph, max_steps=20).execute(plan)

    assert agent.tasks == [plan.description]
    assert agent.apps == [plan.app]
    assert agent.max_steps == [20]


def test_the_goal_check_not_the_agent_decides_success(fake_llm, sample_graph):
    """The agent says done; the goal check sees no note and refuses."""
    agent = ScriptedAgent(steps=[], done=True, final_ui="notes list, empty")
    plan = _plan()
    result = Executor(
        agent, _llm(False, fake_llm), sample_graph
    ).execute(plan)

    assert result.success is False
    assert result.failure_type == "goal_failure"
    assert result.new_trace.metadata["task_description"] == plan.description
    assert result.new_trace.metadata["agent_done"] is True


def test_a_crashing_agent_yields_a_trace_not_an_exception(fake_llm, sample_graph):
    agent = ScriptedAgent(error="adb disconnected")
    result = Executor(agent, _llm(True, fake_llm), sample_graph).execute(_plan())

    assert result.success is False
    assert result.failure_type == "environment_failure"
    assert "adb disconnected" in result.error
    assert result.new_trace is not None


def test_an_explicit_max_steps_overrides_the_configured_budget(
    fake_llm, sample_graph
):
    agent = ScriptedAgent()
    Executor(agent, _llm(True, fake_llm), sample_graph, max_steps=20).execute(
        _plan(), max_steps=5
    )
    assert agent.max_steps == [5]


def test_step_results_carry_no_card_key(fake_llm, sample_graph):
    """Attribution is whole-path now; a step no longer names a card."""
    from specfcg.models import Step

    agent = ScriptedAgent(
        steps=[Step(action="click", target="text=+", success=True)]
    )
    result = Executor(agent, _llm(True, fake_llm), sample_graph).execute(_plan())

    assert result.step_results
    assert all("card" not in item for item in result.step_results)


def test_the_trace_keeps_the_agents_steps(fake_llm, sample_graph):
    from specfcg.models import Step

    agent = ScriptedAgent(
        steps=[
            Step(action="click", target="text=+", before_state="a", after_state="b"),
        ]
    )
    result = Executor(agent, _llm(True, fake_llm), sample_graph).execute(_plan())

    assert [s.target for s in result.new_trace.steps] == ["text=+"]
    assert result.new_trace.start_state == "notes list"


def test_the_backend_carries_its_endpoint_not_the_agent_default():
    """VLM defaults to the Magpie gateway; a local model is not served there."""
    from specfcg.executor.mobile_agent_backend import MobileAgentBackend

    backend = MobileAgentBackend(
        "emulator-5600",
        "Qwen3.8-27B-FP8",
        "Qwen3.8-27B-FP8",
        "runs/smoke",
        base_url="http://127.0.0.1:8002/v1",
        api_key="local",
    )
    assert backend.endpoint == "http://127.0.0.1:8002/v1"
    assert backend.models == ("Qwen3.8-27B-FP8", "Qwen3.8-27B-FP8")


def test_the_backend_carries_the_screen_before_and_after_each_step():
    from specfcg.executor.mobile_agent_backend import MobileAgentBackend

    trace = MobileAgentBackend._convert(
        type(
            "R",
            (),
            {
                "step_records": [
                    {
                        "tool": "tap",
                        "args": {"text": "+"},
                        "ok": True,
                        "ui_before": "notes list",
                        "ui_after": "editor",
                    }
                ],
                "initial_ui": "notes list",
                "final_ui": "editor",
                "error": "",
            },
        )()
    )

    assert trace.steps[0].before_state == "notes list"
    assert trace.steps[0].after_state == "editor"

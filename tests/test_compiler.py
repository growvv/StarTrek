from specfcg.planner.compiler import StepCompiler


def test_compile_steps_parses_actions(fake_llm, two_cards):
    fake_llm.responses = [
        {
            "steps": [
                {"action": "click", "target": "text=Save", "args": ""},
                {"action": "input", "target": "text=Title", "args": "Trip"},
            ]
        }
    ]
    steps = StepCompiler(fake_llm).compile(
        two_cards["create_note"], {"title": "Trip"}
    )
    assert [s.action for s in steps] == ["click", "input"]


def test_compile_falls_back_on_malformed_steps(fake_llm, sample_card):
    fake_llm.responses = ["not json"]
    steps = StepCompiler(fake_llm).compile(sample_card, {"title": "Trip"})
    assert steps
    assert steps[0].action == "click"
    assert all(step.card == sample_card.name for step in steps)


def test_compile_substitutes_bindings(fake_llm, sample_card):
    fake_llm.responses = [
        {
            "steps": [
                {
                    "action": "input",
                    "target": "text=Title",
                    "args": "{title}",
                }
            ]
        }
    ]
    steps = StepCompiler(fake_llm).compile(sample_card, {"title": "Trip"})
    assert steps[0].args == "Trip"

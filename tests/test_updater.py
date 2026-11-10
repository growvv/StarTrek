from specfcg.maintainer.builder import EdgeBuilder
from specfcg.maintainer.updater import GraphUpdater
from specfcg.models import Goal, RunResult, TestPlan as Plan


def test_success_updates_evidence(fake_llm, graph_store, successful_result):
    patch = GraphUpdater(
        fake_llm, graph_store, EdgeBuilder(fake_llm)
    ).update(successful_result)
    assert any(
        update["name"] == "create_note" for update in patch.card_updates
    )
    graph_store.apply_patch(patch)
    assert graph_store.load().cards["create_note"].attempt_count >= 1


def test_invalid_patch_does_not_corrupt_graph(
    fake_llm, graph_store, failed_result
):
    fake_llm.responses = [
        {"card_updates": [{"name": "missing", "fields": {}}]}
    ]
    patch = GraphUpdater(
        fake_llm, graph_store, EdgeBuilder(fake_llm)
    ).update(failed_result)
    assert patch.card_updates == []
    assert "missing" not in graph_store.load().cards


def test_failure_patch_rejects_new_card_with_existing_name(
    fake_llm, graph_store, failed_result
):
    fake_llm.responses = [
        {
            "new_cards": [
                {"name": "create_note", "intent": "replace it"}
            ],
            "reason": "replace",
        }
    ]
    patch = GraphUpdater(
        fake_llm, graph_store, EdgeBuilder(fake_llm)
    ).update(failed_result)
    assert patch.new_cards == []
    assert patch.reason == "invalid patch rejected"


def test_failure_patch_rejects_intent_only_changes(
    fake_llm, graph_store, failed_result
):
    fake_llm.responses = [
        {
            "card_updates": [
                {
                    "name": "create_note",
                    "fields": {
                        "Intent": "Create a note titled Trip and save it."
                    },
                }
            ],
            "reason": "reword the intent",
        }
    ]

    patch = GraphUpdater(
        fake_llm, graph_store, EdgeBuilder(fake_llm)
    ).update(failed_result)

    assert patch.card_updates == []
    assert patch.reason == "invalid patch rejected"


def test_failure_patch_prompt_includes_card_steps_and_actions(
    fake_llm, graph_store, failed_result
):
    failed_result.step_results = [
        {
            "card": "create_note",
            "action": "back",
            "target": "",
            "success": True,
        }
    ]
    fake_llm.responses = [{"reason": "no change"}]

    GraphUpdater(fake_llm, graph_store, EdgeBuilder(fake_llm)).update(
        failed_result
    )

    prompt = fake_llm.prompts[0]
    assert 'Tap "+"' in prompt
    assert "Enter the title" in prompt
    assert "action=back" in prompt


def test_malformed_failure_patch_returns_empty(
    fake_llm, graph_store, failed_result
):
    fake_llm.responses = ["not json"]
    patch = GraphUpdater(
        fake_llm, graph_store, EdgeBuilder(fake_llm)
    ).update(failed_result)
    assert patch.card_updates == []
    assert patch.edge_updates == []


def test_classify_failure_prefers_recorded_type(
    fake_llm, graph_store, failed_result
):
    updater = GraphUpdater(
        fake_llm, graph_store, EdgeBuilder(fake_llm)
    )
    assert updater.classify_failure(failed_result) == "widget_failure"


def test_classify_ambiguous_failure_asks_llm(fake_llm, graph_store):
    result = RunResult(
        plan=Plan(goal=Goal("goal")),
        success=False,
        failure_type=None,
    )
    fake_llm.responses = [{"failure_type": "postcondition_failure"}]
    updater = GraphUpdater(
        fake_llm, graph_store, EdgeBuilder(fake_llm)
    )
    assert updater.classify_failure(result) == "postcondition_failure"

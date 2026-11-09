from specfcg.models import (
    Edge,
    Graph,
    GraphPatch,
    PlanStep,
    RunResult,
    Step,
    TestPlan as Plan,
    Trace,
    Goal,
)


def test_graph_outgoing_returns_edges_from_card(sample_card, another_card):
    edge = Edge(
        from_card="create_note",
        to_card="share_note",
        type="enables",
    )
    graph = Graph(
        cards={"create_note": sample_card, "share_note": another_card},
        edges=[edge],
    )
    assert graph.outgoing("create_note") == [edge]
    assert graph.outgoing("share_note") == []


def test_graph_entry_cards_excludes_cards_with_incoming_edges(
    sample_card, another_card
):
    graph = Graph(
        cards={"create_note": sample_card, "share_note": another_card},
        edges=[
            Edge(
                from_card="create_note",
                to_card="share_note",
                type="sequence",
            )
        ],
    )
    assert graph.entry_cards() == ["create_note"]


def test_graph_patch_defaults_are_independent():
    first = GraphPatch()
    second = GraphPatch()
    first.card_updates.append({"name": "x"})
    assert second.card_updates == []


def test_run_result_records_partial_trace():
    trace = Trace(
        trace_id="t1",
        app="omninotes",
        steps=[Step(action="click", target="Save")],
    )
    plan = Plan(goal=Goal("create a note"), path=["create_note"])
    result = RunResult(
        plan=plan,
        success=False,
        failure_type="widget_failure",
        new_trace=trace,
    )
    assert result.failure_type == "widget_failure"
    assert result.new_trace is trace
    assert result.plan is plan


def test_plan_step_keeps_card_provenance():
    step = PlanStep(card="create_note", action="click", target="text=Save")
    assert step.card == "create_note"

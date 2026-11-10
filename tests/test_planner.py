from specfcg.models import Edge, FunctionCard, Goal, Graph
from specfcg.planner.binding import ParamBinder
from specfcg.planner.compiler import StepCompiler
from specfcg.planner.planner import Planner
from specfcg.planner.retrieval import CardRetriever


def _single_card_graph() -> Graph:
    card = FunctionCard(
        name="act",
        intent="act",
        inputs=[],
        preconditions="",
        postconditions="done",
        effects_outputs="",
        steps=['Tap "Go"'],
    )
    return Graph(cards={"act": card}, edges=[])


def _cyclic_graph() -> Graph:
    cards = {
        name: FunctionCard(
            name=name,
            intent=f"do {name}",
            inputs=[],
            preconditions="",
            postconditions=f"{name} done",
            effects_outputs="",
            steps=["Tap `text=Go`"],
        )
        for name in ("A", "B")
    }
    return Graph(
        cards=cards,
        edges=[
            Edge(from_card="A", to_card="B", type="enables"),
            Edge(from_card="B", to_card="A", type="enables"),
        ],
    )


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
        {
            "cards": [
                {
                    "name": "create_note",
                    "can_execute": True,
                    "is_goal": False,
                },
                {
                    "name": "share_note",
                    "can_execute": False,
                    "is_goal": True,
                },
            ]
        },
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


def test_plan_classifies_all_cards_in_one_llm_call(fake_llm, sample_graph):
    fake_llm.responses = [
        {
            "cards": [
                {
                    "name": "create_note",
                    "can_execute": True,
                    "is_goal": False,
                },
                {
                    "name": "share_note",
                    "can_execute": False,
                    "is_goal": True,
                },
            ]
        },
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
    assert "For each card" in fake_llm.prompts[0]


def test_batch_classification_falls_back_per_card_on_malformed_output(
    fake_llm, sample_graph
):
    fake_llm.responses = [
        "not json",
        {"can_execute": True},
        {"is_goal": False},
        {"is_goal": True},
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


def test_plan_returns_none_when_no_path(fake_llm, sample_graph):
    fake_llm.responses = [
        {
            "cards": [
                {
                    "name": "create_note",
                    "can_execute": False,
                    "is_goal": False,
                },
                {
                    "name": "share_note",
                    "can_execute": False,
                    "is_goal": False,
                },
            ]
        }
    ]
    assert (
        _planner(sample_graph, fake_llm).plan(Goal("impossible"), "start")
        is None
    )


def test_string_false_can_execute_returns_none(fake_llm):
    fake_llm.responses = [{"cards": []}, {"can_execute": "false"}]
    assert (
        _planner(_single_card_graph(), fake_llm).plan(
            Goal("impossible"), "start"
        )
        is None
    )


def test_string_false_is_goal_returns_none(fake_llm):
    fake_llm.responses = [
        {"cards": []},
        {"can_execute": True},
        {"is_goal": "false"},
    ]
    assert (
        _planner(_single_card_graph(), fake_llm).plan(
            Goal("impossible"), "start"
        )
        is None
    )


def test_is_goal_prompt_requires_full_goal(fake_llm):
    fake_llm.responses = [
        {"cards": []},
        {"can_execute": True},
        {"is_goal": False},
    ]
    _planner(_single_card_graph(), fake_llm).plan(
        Goal("create a note then share it"), "start"
    )
    assert "fully satisfy the entire goal" in fake_llm.prompts[2]


def _chain_graph() -> Graph:
    cards = {
        name: FunctionCard(
            name=name,
            intent=f"do {name}",
            inputs=[],
            preconditions="",
            postconditions=f"{name} done",
            effects_outputs="",
            steps=["Tap `text=Go`"],
        )
        for name in ("A", "B", "C")
    }
    return Graph(
        cards=cards,
        edges=[
            Edge(from_card="A", to_card="B", type="enables"),
            Edge(from_card="B", to_card="C", type="enables"),
        ],
    )


def _omninotes_graph() -> Graph:
    cards = {
        "archive_note": FunctionCard(
            name="archive_note",
            intent="Archive the note selected by {target_note}.",
            inputs=["target_note"],
            preconditions="The notes list is visible.",
            postconditions="The note is archived.",
            effects_outputs="Returns to the notes list.",
            steps=["Tap `text=归档`"],
        ),
        "create_note": FunctionCard(
            name="create_note",
            intent="Create a note titled {note_title}.",
            inputs=["note_title", "note_content"],
            preconditions="On the notes list.",
            postconditions="The note is visible in the list.",
            effects_outputs="Returns to the notes list.",
            steps=["Tap `text=New`"],
        ),
        "invoke_share_chooser_for_note": FunctionCard(
            name="invoke_share_chooser_for_note",
            intent="Open the share chooser for the open note.",
            inputs=["note_title"],
            preconditions="The note detail screen is open.",
            postconditions="The share chooser is open.",
            effects_outputs="",
            steps=["Tap `text=共享`"],
        ),
        "open_note_by_title": FunctionCard(
            name="open_note_by_title",
            intent="Open the note titled {note_title}.",
            inputs=["note_title"],
            preconditions="The notes list is visible.",
            postconditions="The note detail screen is open.",
            effects_outputs="",
            steps=["Tap `text={note_title}`"],
        ),
        "search_notes_by_keyword": FunctionCard(
            name="search_notes_by_keyword",
            intent="Search notes for {keyword}.",
            inputs=["keyword"],
            preconditions="The notes list is visible.",
            postconditions="The list is filtered.",
            effects_outputs="",
            steps=["Tap `text=搜索`"],
        ),
    }
    edges = [
        Edge("create_note", "open_note_by_title", "enables"),
        Edge("create_note", "open_note_by_title", "dataflow"),
        Edge("create_note", "invoke_share_chooser_for_note", "dataflow"),
        Edge("create_note", "archive_note", "enables"),
        Edge("create_note", "archive_note", "dataflow"),
        Edge("create_note", "search_notes_by_keyword", "enables"),
        Edge("create_note", "search_notes_by_keyword", "dataflow"),
        Edge("open_note_by_title", "invoke_share_chooser_for_note", "sequence"),
        Edge("open_note_by_title", "invoke_share_chooser_for_note", "enables"),
        Edge("open_note_by_title", "archive_note", "enables"),
        Edge("search_notes_by_keyword", "open_note_by_title", "enables"),
        Edge("search_notes_by_keyword", "archive_note", "enables"),
        Edge("archive_note", "create_note", "enables"),
        Edge("archive_note", "open_note_by_title", "enables"),
        Edge("archive_note", "search_notes_by_keyword", "enables"),
    ]
    return Graph(cards=cards, edges=edges)


def test_plan_composes_real_five_card_graph(fake_llm):
    fake_llm.responses = [
        {
            "cards": [
                {
                    "name": "archive_note",
                    "can_execute": False,
                    "is_goal": False,
                },
                {
                    "name": "create_note",
                    "can_execute": True,
                    "is_goal": False,
                },
                {
                    "name": "invoke_share_chooser_for_note",
                    "can_execute": False,
                    "is_goal": False,
                },
                {
                    "name": "open_note_by_title",
                    "can_execute": False,
                    "is_goal": False,
                },
                {
                    "name": "search_notes_by_keyword",
                    "can_execute": True,
                    "is_goal": False,
                },
            ]
        },
        {"is_goal": False},
        {"is_goal": True},
        {"bindings": {"note_title": "Groceries", "note_content": "Buy milk"}},
        {"bindings": {"target_note": "Groceries"}},
    ]

    plan = _planner(_omninotes_graph(), fake_llm).plan(
        Goal(
            "Create a note titled Groceries with content Buy milk, "
            "then archive it"
        ),
        "OmniNotes notes list",
    )

    assert plan is not None
    assert plan.path == ["create_note", "archive_note"]
    assert "create_note -> open_note_by_title" in fake_llm.prompts[1]
    assert "create_note -> archive_note" in fake_llm.prompts[2]


def test_llm_proposed_plan_avoids_combinatorial_goal_checks(fake_llm):
    fake_llm.responses = [
        {
            "cards": [
                {"name": "A", "can_execute": True, "is_goal": False},
                {"name": "B", "can_execute": False, "is_goal": False},
                {"name": "C", "can_execute": False, "is_goal": False},
            ],
            "plan": [
                {"card": "A", "subgoal": "do A"},
                {"card": "B", "subgoal": "do B"},
                {"card": "C", "subgoal": "do C"},
            ],
        },
        {"is_goal": True},
    ]

    plan = _planner(_chain_graph(), fake_llm).plan(
        Goal("do A then B then C"), "start"
    )

    assert plan is not None
    assert plan.path == ["A", "B", "C"]
    assert len(fake_llm.prompts) == 2
    assert "propose an ordered execution plan" in fake_llm.prompts[0]


def test_proposed_plan_without_graph_edge_falls_back_to_search(fake_llm):
    fake_llm.responses = [
        {
            "cards": [
                {"name": "A", "can_execute": True, "is_goal": False},
                {"name": "B", "can_execute": False, "is_goal": False},
                {"name": "C", "can_execute": False, "is_goal": False},
            ],
            "plan": [
                {"card": "A", "subgoal": "do A"},
                {"card": "C", "subgoal": "do C"},
            ],
        },
        {"is_goal": False},
        {"is_goal": True},
    ]

    plan = _planner(_chain_graph(), fake_llm).plan(
        Goal("do A then B then C"), "start"
    )

    assert plan is not None
    assert plan.path == ["A", "B", "C"]
    assert "A -> B" in fake_llm.prompts[1]


def test_plan_proposal_uses_subgoal_for_each_binding(fake_llm):
    graph = _chain_graph()
    graph.cards["A"] = FunctionCard(
        name="A",
        intent="create note {title}",
        inputs=["title"],
        preconditions="",
        postconditions="note exists",
        effects_outputs="",
        steps=["Tap `text={title}`"],
    )
    fake_llm.responses = [
        {
            "cards": [
                {"name": "A", "can_execute": True, "is_goal": False},
                {"name": "B", "can_execute": False, "is_goal": False},
                {"name": "C", "can_execute": False, "is_goal": False},
            ],
            "plan": [
                {"card": "A", "subgoal": "create note Alpha"},
                {"card": "B", "subgoal": "do B"},
                {"card": "C", "subgoal": "do C"},
            ],
        },
        {"is_goal": True},
        {"bindings": {"title": "Alpha"}},
    ]

    plan = _planner(graph, fake_llm).plan(
        Goal("create note Alpha then B then C"), "start"
    )

    assert plan is not None
    assert plan.path == ["A", "B", "C"]
    assert "create note Alpha" in fake_llm.prompts[2]
    assert plan.steps[0].target == "text=Alpha"


def test_proposal_can_repeat_a_card_with_distinct_subgoals(fake_llm):
    graph = Graph(
        cards={
            "A": FunctionCard(
                name="A",
                intent="create note {title}",
                inputs=["title"],
                preconditions="",
                postconditions="note exists",
                effects_outputs="",
                steps=["Tap `text={title}`"],
            ),
            "B": FunctionCard(
                name="B",
                intent="finish",
                inputs=[],
                preconditions="",
                postconditions="done",
                effects_outputs="",
                steps=["Tap `text=Done`"],
            ),
        },
        edges=[Edge(from_card="A", to_card="B", type="enables")],
    )
    fake_llm.responses = [
        {
            "cards": [
                {"name": "A", "can_execute": True, "is_goal": False},
                {"name": "B", "can_execute": False, "is_goal": False},
            ],
            "plan": [
                {"card": "A", "subgoal": "create note Alpha"},
                {"card": "A", "subgoal": "create note Beta"},
                {"card": "B", "subgoal": "finish"},
            ],
        },
        {"is_goal": True},
        {"bindings": {"title": "Alpha"}},
        {"bindings": {"title": "Beta"}},
    ]

    plan = _planner(graph, fake_llm).plan(
        Goal("create Alpha and Beta then finish"), "start"
    )

    assert plan is not None
    assert plan.path == ["A", "A", "B"]
    assert [step.target for step in plan.steps] == [
        "text=Alpha",
        "text=Beta",
        "text=Done",
    ]
    assert "create note Beta" in fake_llm.prompts[3]


def test_plan_seeds_from_executable_cards_even_with_cycles(fake_llm):
    fake_llm.responses = [
        {
            "cards": [
                {
                    "name": "A",
                    "can_execute": True,
                    "is_goal": False,
                },
                {
                    "name": "B",
                    "can_execute": False,
                    "is_goal": True,
                },
            ]
        },
        {"is_goal": True},
    ]

    plan = _planner(_cyclic_graph(), fake_llm).plan(
        Goal("do B"), "start"
    )

    assert plan is not None
    assert plan.path == ["A", "B"]
    assert "A -> B" in fake_llm.prompts[1]


def test_plan_goal_cache_is_scoped_to_the_goal(fake_llm):
    fake_llm.responses = [
        {
            "cards": [
                {"name": "A", "can_execute": True, "is_goal": False},
                {"name": "B", "can_execute": False, "is_goal": True},
            ]
        },
        {"is_goal": True},
        {
            "cards": [
                {"name": "A", "can_execute": True, "is_goal": False},
                {"name": "B", "can_execute": False, "is_goal": False},
            ]
        },
        {"is_goal": False},
    ]
    planner = _planner(_cyclic_graph(), fake_llm)

    first = planner.plan(Goal("do B"), "start")
    second = planner.plan(Goal("do nothing related"), "start")

    assert first is not None and first.path == ["A", "B"]
    assert second is None


def test_plan_rejects_multi_card_path_that_does_not_complete_goal(
    fake_llm,
):
    fake_llm.responses = [
        {
            "cards": [
                {
                    "name": "A",
                    "can_execute": True,
                    "is_goal": False,
                },
                {
                    "name": "B",
                    "can_execute": False,
                    "is_goal": True,
                },
            ]
        },
        {"is_goal": False},
    ]

    assert (
        _planner(_cyclic_graph(), fake_llm).plan(Goal("do B"), "start")
        is None
    )

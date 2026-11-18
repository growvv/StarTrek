from specfcg.models import Edge, FunctionCard, Goal, Graph
from specfcg.planner.binding import ParamBinder
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
        {"bindings": {}},
    ]
    plan = _planner(sample_graph, fake_llm).plan(
        Goal("create and share a note"), "start"
    )
    assert plan is not None
    assert plan.path == ["create_note", "share_note"]
    assert plan.description.startswith("Overall goal: create and share a note")
    assert "1. create_note" in plan.description
    assert "2. share_note" in plan.description


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
        {"bindings": {}},
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
        {"bindings": {}},
    ]
    plan = _planner(sample_graph, fake_llm).plan(
        Goal("create and share a note"), "start"
    )
    assert plan is not None
    assert plan.path == ["create_note", "share_note"]


def test_plan_prompt_states_the_rule_the_validator_applies(fake_llm):
    """A step the current screen already enables needs no predecessor.  The
    prompt must say so: otherwise the model drops the second independent
    step and the goal is left with a partial plan."""
    graph = Graph(
        cards={
            "start": FunctionCard(
                name="start", intent="start", inputs=[], preconditions="",
                postconditions="", effects_outputs="",
            ),
            "open": FunctionCard(
                name="open", intent="open", inputs=[], preconditions="",
                postconditions="", effects_outputs="",
            ),
        },
        edges=[],
    )
    fake_llm.responses = [
        {
            "cards": [
                {"name": "start", "can_execute": False, "is_goal": False},
                {"name": "open", "can_execute": False, "is_goal": False},
            ]
        }
    ]

    _planner(graph, fake_llm).plan(Goal("start then open"), "home")

    assert "executable in the current state" in fake_llm.prompts[0]


def test_plan_accepts_a_step_the_current_state_already_enables(fake_llm):
    """A step is reachable when the screen already satisfies its
    preconditions; it does not need an edge from an earlier step.

    Two cards can both be executable from the same screen (start recording
    an activity, open the drawer).  Demanding an execution edge between them
    rejects the plan the state itself makes valid, and the goal is left with
    no plan even though both steps run.
    """

    def card(name: str) -> FunctionCard:
        return FunctionCard(
            name=name, intent=f"do {name}", inputs=[], preconditions="",
            postconditions="", effects_outputs="",
        )

    graph = Graph(
        cards={name: card(name) for name in ("start", "search")},
        edges=[],
    )
    fake_llm.responses = [
        {
            "cards": [
                {"name": "start", "can_execute": True, "is_goal": False},
                {"name": "search", "can_execute": True, "is_goal": False},
            ],
            "plan": [
                {"card": "start", "subgoal": "start recording"},
                {"card": "search", "subgoal": "search for it"},
            ],
        },
    ]

    plan = _planner(graph, fake_llm).plan(
        Goal("start recording, then search for it"), "home"
    )

    assert plan is not None and plan.path == ["start", "search"]


def test_planning_expands_candidates_with_graph_connectors(fake_llm):
    """Retrieval picks goal-shaped cards; the graph supplies the bridges.

    A step that must happen between two goal-shaped cards (returning to the
    list before searching) rarely resembles the goal text, so keyword
    retrieval drops it.  Dropping a bridge makes the graph's own routes
    unplannable; the candidate set is closed under execution predecessors.
    """

    def card(name: str) -> FunctionCard:
        return FunctionCard(
            name=name, intent=f"do {name}", inputs=[], preconditions="",
            postconditions="", effects_outputs="",
        )

    graph = Graph(
        cards={name: card(name) for name in ("start", "bridge", "target")},
        edges=[
            Edge(from_card="start", to_card="bridge", type="enables"),
            Edge(from_card="bridge", to_card="target", type="enables"),
        ],
    )
    planner = _planner(graph, fake_llm)
    planner.retriever = type(
        "R", (), {"retrieve": lambda self, goal, cards: ["start", "target"]}
    )()
    fake_llm.responses = [
        {
            "cards": [
                {"name": "start", "can_execute": True, "is_goal": False},
            ],
            "plan": [
                {"card": "start", "subgoal": "start"},
                {"card": "bridge", "subgoal": "bridge"},
                {"card": "target", "subgoal": "target"},
            ],
        },
    ]

    plan = planner.plan(Goal("start then bridge then target"), "screen")

    assert plan is not None and plan.path == ["start", "bridge", "target"]
    # The batch prompt must show the bridge card and the edges through it,
    # or the model cannot propose the route the graph already knows.
    assert "- bridge:" in fake_llm.prompts[0]
    assert "- bridge -> target (enables)" in fake_llm.prompts[0]


def test_proposal_is_planned_over_the_graph_edges(fake_llm, sample_graph):
    """The batch prompt carries the execution edges, so its plan is a graph
    plan rather than free-form model improvisation."""
    fake_llm.responses = [
        {
            "cards": [
                {"name": "create_note", "can_execute": True, "is_goal": False},
                {"name": "share_note", "can_execute": False, "is_goal": True},
            ],
            "plan": [
                {"card": "create_note", "subgoal": "create the note"},
                {"card": "share_note", "subgoal": "share it"},
            ],
        },
        {"bindings": {"title": "Trip"}},
        {"bindings": {}},
    ]

    plan = _planner(sample_graph, fake_llm).plan(
        Goal("create and share a note"), "start"
    )

    assert plan is not None and plan.path == ["create_note", "share_note"]
    assert "create_note -> share_note" in fake_llm.prompts[0]


def test_batch_proposal_is_not_certified_again_by_the_same_model(
    fake_llm, sample_graph,
):
    """One model is not independent evidence about its own plan.

    The batch already proposed an ordered plan over the graph; asking the
    same model a second time whether that plan reaches the goal rejects
    valid compositions (and accepts invalid ones like an extra pin step).
    Execution and the benchmark oracle are the verification.
    """
    fake_llm.responses = [
        {
            "cards": [
                {"name": "create_note", "can_execute": True, "is_goal": False},
                {"name": "share_note", "can_execute": False, "is_goal": True},
            ],
            "plan": [
                {"card": "create_note", "subgoal": "create the note"},
                {"card": "share_note", "subgoal": "share it"},
            ],
        },
        {"bindings": {"title": "Trip"}},
        {"bindings": {}},
    ]

    plan = _planner(sample_graph, fake_llm).plan(
        Goal("create and share a note"), "start"
    )

    assert plan is not None and plan.path == ["create_note", "share_note"]
    # batch + one bind per card; there is no compile call and no second
    # certification of the same model's own plan.
    assert fake_llm.calls == 3


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
        ),
        "create_note": FunctionCard(
            name="create_note",
            intent="Create a note titled {note_title}.",
            inputs=["note_title", "note_content"],
            preconditions="On the notes list.",
            postconditions="The note is visible in the list.",
            effects_outputs="Returns to the notes list.",
        ),
        "invoke_share_chooser_for_note": FunctionCard(
            name="invoke_share_chooser_for_note",
            intent="Open the share chooser for the open note.",
            inputs=["note_title"],
            preconditions="The note detail screen is open.",
            postconditions="The share chooser is open.",
            effects_outputs="",
        ),
        "open_note_by_title": FunctionCard(
            name="open_note_by_title",
            intent="Open the note titled {note_title}.",
            inputs=["note_title"],
            preconditions="The notes list is visible.",
            postconditions="The note detail screen is open.",
            effects_outputs="",
        ),
        "search_notes_by_keyword": FunctionCard(
            name="search_notes_by_keyword",
            intent="Search notes for {keyword}.",
            inputs=["keyword"],
            preconditions="The notes list is visible.",
            postconditions="The list is filtered.",
            effects_outputs="",
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
    # One call: the batch that proposed the plan over the graph's edges.
    # No second certification by the same model, and no per-path checks.
    assert len(fake_llm.prompts) == 1
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
    assert "title = Alpha" in plan.description
    assert plan.description.index("1. A") < plan.description.index("2. B")


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
            ),
            "B": FunctionCard(
                name="B",
                intent="finish",
                inputs=[],
                preconditions="",
                postconditions="done",
                effects_outputs="",
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
    # The same card twice, with the value each instance was bound to.
    assert plan.description.count("1. A") == 1
    assert "2. A" in plan.description
    assert "title = Alpha" in plan.description
    assert "title = Beta" in plan.description
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


def test_compile_path_plans_exactly_the_path_it_is_given(fake_llm):
    """A probe predicted a path; executing it must not re-search.

    The calibration metric compares a path's predicted confidence against
    whether that path reached the function.  If the runner searched again,
    the executed path would be a different one, and the comparison would say
    nothing about the estimate.
    """
    fake_llm.responses = [
        {"bindings": {"note_title": "Groceries", "note_content": "Buy milk"}},
        {"bindings": {"note_title": "Groceries"}},
    ]
    planner = _planner(_omninotes_graph(), fake_llm)

    plan = planner.compile_path(
        Goal("Create a note and share it"),
        ["create_note", "invoke_share_chooser_for_note"],
        ["Create a note", "Share it"],
        "OmniNotes notes list",
    )

    assert plan is not None
    assert plan.path == ["create_note", "invoke_share_chooser_for_note"]
    assert "1. create_note" in plan.description
    assert "2. invoke_share_chooser_for_note" in plan.description
    # No action is named: the agent decides how.
    assert "click" not in plan.description.lower()
    assert "tap" not in plan.description.lower()


def test_compile_path_returns_none_for_a_card_the_graph_does_not_have(
    fake_llm,
):
    """A predicted path may end at a card that does not exist yet.

    An uncovered function's route stops at a gateway card; the function
    itself has no card, so there is nothing to compile.  That is a no-plan,
    not a crash.
    """
    planner = _planner(_omninotes_graph(), fake_llm)

    assert (
        planner.compile_path(
            Goal("Open settings"),
            ["open_navigation_drawer"],
            ["Open settings"],
            "notes list",
        )
        is None
    )

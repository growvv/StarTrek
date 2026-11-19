from specfcg.cards.store import CardStore
from specfcg.maintainer.miner import CardMiner
from specfcg.models import Step, Trace


def test_segment_returns_llm_boundaries(tmp_path, fake_llm, sample_trace):
    fake_llm.responses = [
        {
            "episodes": [
                {
                    "start": 0,
                    "end": 1,
                    "name": "create_note",
                    "intent": "create a note",
                },
                {
                    "start": 2,
                    "end": 3,
                    "name": "share_note",
                    "intent": "share a note",
                },
            ]
        }
    ]
    segments = CardMiner(fake_llm, CardStore(tmp_path)).segment(sample_trace)
    assert [s["name"] for s in segments] == ["create_note", "share_note"]


def test_segment_invalid_boundaries_falls_back_to_single_episode(
    tmp_path, fake_llm, sample_trace
):
    fake_llm.responses = [{"episodes": [{"start": 5, "end": 99}]}]
    segments = CardMiner(fake_llm, CardStore(tmp_path)).segment(sample_trace)
    assert len(segments) == 1
    assert segments[0]["start"] == 0


def test_mine_empty_trace_returns_empty_patch(tmp_path, fake_llm, empty_trace):
    patch = CardMiner(fake_llm, CardStore(tmp_path)).mine(empty_trace)
    assert patch.new_cards == [] and patch.segments == []


def test_mine_single_step_trace_produces_card(
    tmp_path, fake_llm, single_step_trace
):
    fake_llm.responses = [
        {
            "episodes": [
                {
                    "start": 0,
                    "end": 0,
                    "name": "open_app",
                    "intent": "open the app",
                }
            ]
        },
        "# open_app\n\n**Intent**: open the app\n**Inputs**: none\n"
        "**Preconditions**: app closed\n**Postconditions**: app is open\n"
        "**Effects/Outputs**: none\n"
        "**Evidence**: traces t1; 1/1 successes",
    ]
    patch = CardMiner(fake_llm, CardStore(tmp_path)).mine(single_step_trace)
    assert patch.new_cards[0].name == "open_app"


def test_draft_returns_none_on_malformed_markdown(
    tmp_path, fake_llm, sample_trace
):
    """No contract, no card: a fallback built from the trace is a transcript."""
    fake_llm.responses = ["not a card"]
    miner = CardMiner(fake_llm, CardStore(tmp_path))
    episode = {
        "start": 0,
        "end": 1,
        "name": "create_note",
        "intent": "create a note",
    }
    assert miner.draft(episode, sample_trace) is None


def test_mine_skips_an_episode_with_no_contract(
    tmp_path, fake_llm, sample_trace
):
    fake_llm.responses = [
        {"episodes": [{"start": 0, "end": 3, "name": "create_note", "intent": "x"}]},
        "not a card",
    ]
    patch = CardMiner(fake_llm, CardStore(tmp_path)).mine(sample_trace)
    assert patch.new_cards == []
    assert patch.segments == []


def test_mine_merges_existing_card_evidence(
    tmp_path, fake_llm, sample_trace, sample_card
):
    cards = CardStore(tmp_path)
    cards.save(sample_card)
    fake_llm.responses = [
        {
            "episodes": [
                {
                    "start": 0,
                    "end": 3,
                    "name": sample_card.name,
                    "intent": "create a note",
                }
            ]
        },
        "# create_note\n\n**Intent**: create a note\n**Inputs**: title\n"
        "**Preconditions**: on list\n**Postconditions**: note exists\n"
        "**Effects/Outputs**: note\n"
        "**Evidence**: traces t1; 1/1 successes",
    ]
    patch = CardMiner(fake_llm, cards).mine(sample_trace)
    assert patch.new_cards == []
    assert patch.updates[0]["name"] == sample_card.name
    assert "t1" in patch.updates[0]["fields"]["evidence"]
    assert (
        patch.updates[0]["fields"]["attempt_count"]
        == sample_card.attempt_count + 1
    )


def _input_trace() -> Trace:
    return Trace(
        trace_id="t9",
        app="omninotes",
        start_state="Notes list",
        goal="create a note",
        steps=[
            Step(
                action="click",
                target="resourceId=it.feio:id/fab_note",
                before_state="Notes list",
                after_state="Editor",
            ),
            Step(
                action="input",
                target="resourceId=it.feio:id/detail_title",
                args="Grocery list",
                before_state="Editor",
                after_state="Editor",
            ),
            Step(
                action="input",
                target="resourceId=it.feio:id/detail_content",
                args="Buy milk and eggs",
                before_state="Editor",
                after_state="Editor",
            ),
        ],
    )


def test_draft_declares_placeholders_the_model_left_undeclared(
    tmp_path, fake_llm
):
    """A {name} the contract uses must be an input, or nothing can bind it."""
    fake_llm.responses = [
        "# create_text_note\n\n**Intent**: create a note titled {note_title}\n"
        "**Inputs**: none\n**Preconditions**: on the notes list\n"
        "**Postconditions**: a note titled {note_title} exists\n"
        "**Effects/Outputs**: note\n"
        "**Evidence**: traces t9; 1/1 successes"
    ]
    miner = CardMiner(fake_llm, CardStore(tmp_path))
    card = miner.draft(
        {"start": 0, "end": 2, "name": "create_text_note", "intent": ""},
        _input_trace(),
    )

    assert [item.split()[0] for item in card.inputs] == ["note_title"]


def test_draft_keeps_the_inputs_the_model_declared(tmp_path, fake_llm):
    fake_llm.responses = [
        "# create_text_note\n\n**Intent**: create a note titled {note_title}\n"
        "**Inputs**:\n- note_title (required): the title\n"
        "**Preconditions**: on the notes list\n"
        "**Postconditions**: a note titled {note_title} exists\n"
        "**Effects/Outputs**: note\n"
        "**Evidence**: traces t9; 1/1 successes"
    ]
    miner = CardMiner(fake_llm, CardStore(tmp_path))
    card = miner.draft(
        {"start": 0, "end": 2, "name": "create_text_note", "intent": ""},
        _input_trace(),
    )

    assert [item.split()[0] for item in card.inputs] == ["note_title"]


def _select_and_delete_trace() -> Trace:
    return Trace(
        trace_id="t10",
        app="amaze",
        start_state=(
            "TextView text='bench_new.txt' id='app:id/firstline' "
            "bounds='[184,1311][491,1376]'\n"
            "RelativeLayout id='app:id/second' clickable=true "
            "bounds='[0,1300][1008,1500]'"
        ),
        goal="Select a file and delete it",
        steps=[
            Step(
                action="long_click",
                target="text=bench_new.txt",
                before_state=(
                    "TextView text='bench_new.txt' "
                    "id='app:id/firstline' bounds='[184,1311][491,1376]'"
                ),
                after_state="Selection mode",
            ),
            Step(
                action="click",
                target="desc=Delete",
                before_state=(
                    "Button id='app:id/delete' desc='Delete' clickable=true "
                    "bounds='[662,159][784,281]'"
                ),
                after_state="Confirm dialog",
            ),
        ],
    )


def test_a_trace_value_baked_into_the_contract_becomes_an_input(
    tmp_path, fake_llm
):
    """The model writes the run's own file name into the postcondition.

    A contract that promises ``bench_new.txt is gone`` promises one run's
    outcome; the next run deletes a different file.  The start screen proves
    the value is data, so it becomes {item_label}.
    """
    fake_llm.responses = [
        "# delete_file\n\n**Intent**: select and delete a file\n"
        "**Inputs**: none\n**Preconditions**: on a folder listing\n"
        "**Postconditions**: bench_new.txt is gone\n"
        "**Effects/Outputs**: deleted\n"
        "**Evidence**: traces t10; 1/1 successes"
    ]
    miner = CardMiner(fake_llm, CardStore(tmp_path))
    card = miner.draft(
        {"start": 0, "end": 1, "name": "delete_file", "intent": ""},
        _select_and_delete_trace(),
    )

    assert [item.split()[0] for item in card.inputs] == ["item_label"]
    assert "bench_new.txt" not in card.postconditions
    assert "{item_label}" in card.postconditions


def test_a_control_label_in_the_contract_stays_literal(tmp_path, fake_llm):
    """A menu label is the function's vocabulary, not a caller input.

    ``Delete`` is on a screen the function itself opens, so the start screen
    never shows it as content and it is not generalised.
    """
    fake_llm.responses = [
        "# delete_file\n\n**Intent**: select and delete a file\n"
        "**Inputs**: none\n**Preconditions**: on a folder listing\n"
        "**Postconditions**: the file is gone after Delete\n"
        "**Effects/Outputs**: deleted\n"
        "**Evidence**: traces t10; 1/1 successes"
    ]
    miner = CardMiner(fake_llm, CardStore(tmp_path))
    card = miner.draft(
        {"start": 0, "end": 1, "name": "delete_file", "intent": ""},
        _select_and_delete_trace(),
    )

    assert "Delete" in card.postconditions
    assert "{item_label}" not in card.postconditions


def test_a_launch_screen_value_is_data_not_build_wording(tmp_path, fake_llm):
    """A value the launch screen already shows is this run's data."""
    trace = Trace(
        trace_id="t13",
        app="omninotes",
        start_state="TextView text='Grocery list' id='app:id/note_title'",
        goal="Open the note named in the goal",
        steps=[
            Step(
                action="click",
                target="text=Grocery list",
                before_state="TextView text='Grocery list' id='app:id/note_title'",
                after_state="detail screen",
            ),
        ],
    )
    fake_llm.responses = [
        "# open_note\n\n**Intent**: open the note Grocery list\n"
        "**Inputs**: note_title (required): the note to open\n"
        "**Preconditions**: on the notes list\n"
        "**Postconditions**: Grocery list is open\n"
        "**Effects/Outputs**: none\n"
        "**Evidence**: traces t13; 1/1 successes"
    ]
    miner = CardMiner(fake_llm, CardStore(tmp_path))
    card = miner.draft(
        {"start": 0, "end": 0, "name": "open_note", "intent": ""},
        trace,
    )

    assert "Grocery list" not in card.intent
    assert "Grocery list" not in card.postconditions
    assert any(item.startswith("item_label") for item in card.inputs)
def _episode() -> dict:
    return {"start": 0, "end": 3, "name": "create_note", "intent": "create a note"}


def _card(**overrides) -> str:
    fields = {
        "Intent": "Create a note titled {note_title}.",
        "Inputs": "- note_title (required): the title",
        "Preconditions": "The notes list is open.",
        "Postconditions": "A note titled {note_title} exists.",
        "Effects/Outputs": "The note is saved.",
        "Evidence": "traces t1; 1/1 successes",
    }
    fields.update(overrides)
    body = "\n".join(f"**{key}**: {value}" for key, value in fields.items())
    return f"# create_note\n\n{body}\n"


def test_card_prompt_asks_for_a_contract_not_a_script(
    tmp_path, fake_llm, sample_trace
):
    fake_llm.responses = [_card()]
    CardMiner(fake_llm, CardStore(tmp_path)).draft(_episode(), sample_trace)
    prompt = fake_llm.prompts[-1]
    assert "**Steps**" not in prompt
    assert "**Postconditions**" in prompt and "**Preconditions**" in prompt


def test_an_unparseable_card_yields_no_card(tmp_path, fake_llm, sample_trace):
    fake_llm.responses = ["I cannot write this card."]
    assert CardMiner(fake_llm, CardStore(tmp_path)).draft(
        _episode(), sample_trace
    ) is None


def test_a_trace_value_baked_into_the_contract_becomes_an_input(
    tmp_path, fake_llm, sample_trace
):
    # The model writes the run's own value into the postcondition instead of a
    # placeholder; the start screen proves it is data.
    fake_llm.responses = [
        _card(Postconditions="A note titled Trip exists on the notes list.")
    ]
    trace = sample_trace
    trace.start_state = (
        "TextView text='Trip' resourceId='app:id/note_title'"
    )
    card = CardMiner(fake_llm, CardStore(tmp_path)).draft(_episode(), trace)
    assert card is not None
    assert "Trip" not in card.postconditions
    assert any(item.startswith("item_label") for item in card.inputs)


def test_a_trace_whose_actions_all_failed_yields_no_card(
    tmp_path, fake_llm, sample_trace
):
    """A failed trace records what the app did not do.

    The quicknote trace collected on a build whose controls had moved had
    three failed actions, and the miner still wrote a `write_quick_note` card
    from it — a function nobody had seen work.
    """
    for step in sample_trace.steps:
        step.success = False
    fake_llm.responses = [
        {"episodes": [{"start": 0, "end": 3, "name": "create_note", "intent": "x"}]},
        _card(),
    ]

    patch = CardMiner(fake_llm, CardStore(tmp_path)).mine(sample_trace)

    assert patch.new_cards == []


def test_a_single_episode_keeps_the_trace_authors_declared_name():
    """A trace is written to exercise one function, and its spec may name it.

    The model named a QuickNote-open trace `open_main_tab` after the screen it
    saw; the spec declared `open_quicknote`.  The generic name matched no
    inventory entry, so a function that had been traced read as missing.
    """
    from specfcg.maintainer.miner import _name_from_goal

    trace = Trace(
        trace_id="t1",
        app="markor",
        goal="Open QuickNote",
        function_name="open_quicknote",
        steps=[],
    )

    named = _name_from_goal(
        [{"start": 0, "end": 0, "name": "open_main_tab", "intent": "x"}], trace
    )

    assert named[0]["name"] == "open_quicknote"
    assert named[0]["start"] == 0 and named[0]["end"] == 0


def test_two_episodes_keep_the_models_names():
    """Only a trace that is one function keeps the goal name."""
    from specfcg.maintainer.miner import _name_from_goal

    trace = Trace(
        trace_id="t2", app="app", goal="Do two things",
        function_name="do_two_things", steps=[],
    )
    episodes = [
        {"start": 0, "end": 0, "name": "first_thing", "intent": "a"},
        {"start": 1, "end": 1, "name": "second_thing", "intent": "b"},
    ]

    assert _name_from_goal(episodes, trace) == episodes


def test_a_trace_without_a_declared_name_keeps_the_models_name():
    from specfcg.maintainer.miner import _name_from_goal

    trace = Trace(trace_id="t3", app="app", goal="", steps=[])

    assert _name_from_goal(
        [{"start": 0, "end": 0, "name": "something", "intent": "x"}], trace
    )[0]["name"] == "something"


def test_a_prose_goal_does_not_become_a_card_name():
    """`create and share a note` is a task phrase, not a function name."""
    from specfcg.maintainer.miner import _name_from_goal

    trace = Trace(
        trace_id="t4", app="app", goal="create and share a note", steps=[]
    )

    assert _name_from_goal(
        [{"start": 0, "end": 0, "name": "create_note", "intent": "x"}], trace
    )[0]["name"] == "create_note"


def test_the_goal_name_is_asked_for_in_the_card_prompt(fake_llm, sample_trace):
    """Renaming the episode is not enough: the card's own heading is its name."""
    from specfcg.maintainer.miner import CardMiner

    class Store:
        def all(self):
            return {}

    fake_llm.responses = [_card()]
    miner = CardMiner(fake_llm, Store())
    miner.draft(
        {"start": 0, "end": 0, "name": "open_quicknote",
         "intent": "x", "expected_name": "open_quicknote"},
        sample_trace,
    )

    assert "The first line must be exactly '# open_quicknote'." in fake_llm.prompts[-1]


def test_a_card_the_model_misnamed_is_renamed_to_the_goal(fake_llm, sample_trace):
    """The model ignoring the instruction must not rename a traced function.

    It wrote `# open_main_tab` for a trace whose goal was "Open QuickNote";
    the generic name matched no inventory entry.
    """
    from specfcg.maintainer.miner import CardMiner

    class Store:
        def all(self):
            return {}

    fake_llm.responses = [_card()]  # this helper's card is titled create_note
    card = CardMiner(fake_llm, Store()).draft(
        {"start": 0, "end": 0, "name": "open_quicknote",
         "intent": "x", "expected_name": "open_quicknote"},
        sample_trace,
    )

    assert card is not None
    assert card.name == "open_quicknote"


def test_the_fallback_episode_takes_the_declared_name_too(
    tmp_path, fake_llm
):
    """A one-step trace often fails segmentation, and must not lose its name."""
    from specfcg.maintainer.miner import CardMiner

    trace = Trace(
        trace_id="t9",
        app="markor",
        goal="Open QuickNote",
        function_name="open_quicknote",
        steps=[Step(action="click", target="desc=QuickNote", success=True)],
    )
    # Invalid boundaries force the fallback episode.
    fake_llm.responses = [{"episodes": [{"start": 0, "end": 5, "name": "x"}]}]

    class Store:
        def all(self):
            return {}

    episodes = CardMiner(fake_llm, Store()).segment(trace)

    assert episodes[0]["name"] == "open_quicknote"
    assert episodes[0]["expected_name"] == "open_quicknote"


def test_the_digest_covers_the_declared_name():
    """Adding a name to a spec changes what is mined, so it changes the digest.

    Without it the pipeline reported the trace as already mined and kept the
    model's own card name.
    """
    from specfcg.traces.recorder import trace_digest

    steps = [Step(action="click", target="desc=QuickNote", success=True)]
    named = Trace(
        trace_id="t", app="markor", goal="Open QuickNote",
        function_name="open_quicknote", steps=steps,
    )
    unnamed = Trace(
        trace_id="t", app="markor", goal="Open QuickNote", steps=steps,
    )

    assert trace_digest(named) != trace_digest(unnamed)


def test_the_declared_name_is_enforced_even_when_segmentation_agrees():
    """The model named the episode right and the card wrong.

    Segmentation said `open_quicknote`; the card draft still wrote
    `activate_tab`.  `expected_name` is what makes the card follow.
    """
    from specfcg.maintainer.miner import _name_from_goal

    trace = Trace(
        trace_id="t5", app="markor", goal="Open QuickNote",
        function_name="open_quicknote", steps=[],
    )

    named = _name_from_goal(
        [{"start": 0, "end": 0, "name": "open_quicknote", "intent": "x"}], trace
    )

    assert named[0]["expected_name"] == "open_quicknote"

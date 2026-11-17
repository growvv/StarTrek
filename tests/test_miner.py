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
        "**Effects/Outputs**: none\n**Steps**:\n1. Tap the icon\n"
        "**Evidence**: traces t1; 1/1 successes",
    ]
    patch = CardMiner(fake_llm, CardStore(tmp_path)).mine(single_step_trace)
    assert patch.new_cards[0].name == "open_app"


def test_draft_falls_back_on_malformed_markdown(
    tmp_path, fake_llm, sample_trace
):
    fake_llm.responses = ["not a card"]
    miner = CardMiner(fake_llm, CardStore(tmp_path))
    episode = {
        "start": 0,
        "end": 1,
        "name": "create_note",
        "intent": "create a note",
    }
    card = miner.draft(episode, sample_trace)
    assert card.name == "create_note"
    # the typed value is declared as an input instead of being dropped
    assert card.steps == ["click text=+", "input text=Title {title}"]
    assert card.inputs == ["title (required): value typed into text=Title"]


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
        "**Effects/Outputs**: note\n**Steps**:\n1. Tap +\n"
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


def test_draft_declares_inputs_the_model_left_unspecified(
    tmp_path, fake_llm
):
    fake_llm.responses = [
        "# create_text_note\n\n**Intent**: create a text note\n"
        "**Inputs**: none\n**Preconditions**: on the notes list\n"
        "**Postconditions**: a note exists\n**Effects/Outputs**: note\n"
        "**Steps**:\n"
        "1. click resourceId=it.feio:id/fab_note\n"
        "2. input resourceId=it.feio:id/detail_title\n"
        "3. input resourceId=it.feio:id/detail_content\n"
        "**Evidence**: traces t9; 1/1 successes"
    ]
    miner = CardMiner(fake_llm, CardStore(tmp_path))
    card = miner.draft(
        {"start": 0, "end": 2, "name": "create_text_note", "intent": ""},
        _input_trace(),
    )

    assert [item.split()[0] for item in card.inputs] == ["title", "content"]
    assert "{title}" in card.steps[1]
    assert "{content}" in card.steps[2]


def test_draft_keeps_the_model_inputs_when_it_declared_them(
    tmp_path, fake_llm
):
    fake_llm.responses = [
        "# create_text_note\n\n**Intent**: create a text note\n"
        "**Inputs**:\n- note_title (required): the title\n"
        "**Preconditions**: on the notes list\n"
        "**Postconditions**: a note exists\n**Effects/Outputs**: note\n"
        "**Steps**:\n"
        "1. click resourceId=it.feio:id/fab_note\n"
        "2. input resourceId=it.feio:id/detail_title {note_title}\n"
        "3. input resourceId=it.feio:id/detail_content\n"
        "**Evidence**: traces t9; 1/1 successes"
    ]
    miner = CardMiner(fake_llm, CardStore(tmp_path))
    card = miner.draft(
        {"start": 0, "end": 2, "name": "create_text_note", "intent": ""},
        _input_trace(),
    )

    assert [item.split()[0] for item in card.inputs] == ["note_title", "content"]
    assert "{note_title}" in card.steps[1]
    assert "{content}" in card.steps[2]


def test_fallback_card_declares_trace_inputs(tmp_path, fake_llm):
    fake_llm.responses = ["not a card"]
    miner = CardMiner(fake_llm, CardStore(tmp_path))
    card = miner.draft(
        {"start": 0, "end": 2, "name": "create_text_note", "intent": ""},
        _input_trace(),
    )

    assert [item.split()[0] for item in card.inputs] == ["title", "content"]
    assert card.steps[1].endswith("{title}")
    assert card.steps[2].endswith("{content}")


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
                    "id='app:id/firstline' bounds='[184,1311][491,1376]'\n"
                    "RelativeLayout id='app:id/second' clickable=true "
                    "bounds='[0,1300][1008,1500]'"
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


def test_draft_turns_a_baked_in_tap_target_into_a_declared_input(
    tmp_path, fake_llm
):
    """A control named by the file it shows is the trace's data, not the
    function's identity.

    The trace long-clicked bench_new.txt; a card that keeps that literal can
    only ever delete bench_new.txt, and the benchmark's own delete task
    (bench_delete.txt) is then unplannable.  The value belongs in an input.
    """
    fake_llm.responses = [
        "# delete_file\n\n**Intent**: select and delete a file\n"
        "**Inputs**: none\n**Preconditions**: on a folder listing\n"
        "**Postconditions**: the file is gone\n**Effects/Outputs**: deleted\n"
        "**Steps**:\n"
        "1. long_click text=bench_new.txt\n"
        "2. click desc=Delete\n"
        "**Evidence**: traces t10; 1/1 successes"
    ]
    miner = CardMiner(fake_llm, CardStore(tmp_path))
    card = miner.draft(
        {"start": 0, "end": 1, "name": "delete_file", "intent": ""},
        _select_and_delete_trace(),
    )

    assert [item.split()[0] for item in card.inputs] == ["item_label"]
    assert card.steps[0] == "long_click text={item_label}"
    assert card.steps[1] == "click desc=Delete"


def test_draft_leaves_a_control_label_that_does_not_come_from_the_trace(
    tmp_path, fake_llm
):
    """Only the trace's own value is generalised; menu labels stay literal."""
    fake_llm.responses = [
        "# delete_file\n\n**Intent**: select and delete a file\n"
        "**Inputs**: none\n**Preconditions**: on a folder listing\n"
        "**Postconditions**: the file is gone\n**Effects/Outputs**: deleted\n"
        "**Steps**:\n"
        "1. long_click text=bench_new.txt\n"
        "2. click desc=Delete\n"
        "**Evidence**: traces t10; 1/1 successes"
    ]
    miner = CardMiner(fake_llm, CardStore(tmp_path))
    card = miner.draft(
        {"start": 0, "end": 1, "name": "delete_file", "intent": ""},
        _select_and_delete_trace(),
    )

    assert "Delete" in card.steps[1]
    assert "{Delete}" not in card.steps[1]


def test_draft_binds_a_menu_label_that_appeared_after_the_start_screen(
    tmp_path, fake_llm
):
    """A menu label is the function's own vocabulary, not a caller input.

    The model wrote the overflow item as ``{delete_note_label}`` and declared
    it an input.  No caller can supply it: it is the label the build itself
    puts on the control, and the screen that shows it only exists after an
    earlier step opens the menu.  The binder then has to guess the label from
    the goal -- it guessed "Delete" where the build says "Delete note", and
    the plan tapped a row that does not exist.  The trace names the control,
    so the card must keep that name literal.
    """
    trace = Trace(
        trace_id="t11",
        app="omninotes",
        start_state=(
            "TextView text='Grocery list' "
            "id='app:id/note_title' clickable=true\n"
            "ImageView desc='More options' clickable=true"
        ),
        goal="Delete the open note",
        steps=[
            Step(
                action="click",
                target="text=Grocery list",
                before_state=(
                    "TextView text='Grocery list' "
                    "id='app:id/note_title' clickable=true"
                ),
                after_state="detail screen",
            ),
            Step(
                action="click",
                target="desc=More options",
                before_state=(
                    "ImageView desc='More options' clickable=true"
                ),
                after_state="menu open",
            ),
            Step(
                action="click",
                target="text=Delete note",
                before_state=(
                    "TextView text='Delete note' id='app:id/title' "
                    "clickable=true bounds='[539,817][957,885]'"
                ),
                after_state="notes list",
            ),
        ],
    )
    fake_llm.responses = [
        "# delete_opened_note\n\n"
        "**Intent**: Delete the open note via {delete_note_label}\n"
        "**Inputs**: delete_note_label (required): label of the delete item\n"
        "**Preconditions**: a note is open\n"
        "**Postconditions**: the note is gone\n"
        "**Effects/Outputs**: note deleted\n"
        "**Steps**:\n"
        "1. Tap the note row text='Grocery list'.\n"
        "2. Tap the overflow control desc='More options'.\n"
        "3. Tap the menu item text='{delete_note_label}'.\n"
        "**Evidence**: traces t11; 1/1 successes"
    ]
    miner = CardMiner(fake_llm, CardStore(tmp_path))
    card = miner.draft(
        {"start": 0, "end": 2, "name": "delete_opened_note", "intent": ""},
        trace,
    )

    # The placeholder stays -- the card must still work when a caller names
    # a different label -- but it is optional and carries the label the
    # build actually showed, so a binder with no value from the goal does
    # not have to guess the build's wording.
    declarations = {item.split()[0]: item for item in card.inputs}
    declaration = declarations["delete_note_label"]
    assert declaration.startswith("delete_note_label (optional)")
    assert "observed: 'Delete note'" in declaration
    assert "{delete_note_label}" in card.steps[2]


def test_draft_reads_a_dialog_row_label_from_a_non_clickable_text_view(
    tmp_path, fake_llm
):
    """A dialog row is labelled by its TextView; the row itself handles taps.

    The real trace's delete row is ``TextView text='删除笔记'
    id='...:id/title'`` with no ``clickable=true`` on it -- the dialog item
    around it takes the click.  Requiring the label's own node to be
    clickable therefore missed every dialog menu, and the card fell back to
    guessing the build's wording.
    """
    trace = Trace(
        trace_id="t12",
        app="omninotes",
        start_state=(
            "TextView text='Grocery list' id='app:id/note_title' clickable=true\n"
            "ImageView desc='更多选项' clickable=true"
        ),
        goal="Delete the open note",
        steps=[
            Step(
                action="click",
                target="text=Grocery list",
                before_state=(
                    "TextView text='Grocery list' id='app:id/note_title' "
                    "clickable=true"
                ),
                after_state="detail screen",
            ),
            Step(
                action="click",
                target="desc=更多选项",
                before_state="ImageView desc='更多选项' clickable=true",
                after_state="menu open",
            ),
            Step(
                action="click",
                target="text=删除笔记",
                before_state=(
                    "LinearLayout id='app:id/menu_row' clickable=true "
                    "bounds='[0,817][1008,885]'\n"
                    "TextView text='删除笔记' id='app:id/title' "
                    "bounds='[539,817][957,885]'"
                ),
                after_state="notes list",
            ),
        ],
    )
    fake_llm.responses = [
        "# delete_opened_note\n\n"
        "**Intent**: Delete the open note via {delete_note_label}\n"
        "**Inputs**: delete_note_label (required): label of the delete item\n"
        "**Preconditions**: a note is open\n"
        "**Postconditions**: the note is gone\n"
        "**Effects/Outputs**: note deleted\n"
        "**Steps**:\n"
        "1. Tap the note row text='Grocery list'.\n"
        "2. Tap the overflow control desc='更多选项'.\n"
        "3. Tap the menu item text='{delete_note_label}'.\n"
        "**Evidence**: traces t12; 1/1 successes"
    ]
    miner = CardMiner(fake_llm, CardStore(tmp_path))
    card = miner.draft(
        {"start": 0, "end": 2, "name": "delete_opened_note", "intent": ""},
        trace,
    )

    declarations = {item.split()[0]: item for item in card.inputs}
    assert "observed: '删除笔记'" in declarations["delete_note_label"]


def test_draft_records_the_overflow_label_as_build_wording_too(
    tmp_path, fake_llm
):
    """A button's own label is vocabulary even though the launch screen has it.

    The overflow control is on the screen before the function runs, so its
    label is not something the function discovered -- but it is still the
    build's wording for a control, not a value the caller chooses.  What
    separates the two is how the launch screen shows the value: as content
    (a note title) or as a control's own label (a button description).
    """
    trace = Trace(
        trace_id="t14",
        app="omninotes",
        start_state=(
            "TextView text='Grocery list' id='app:id/note_title'\n"
            "ImageView desc='More options' clickable=true"
        ),
        goal="Delete the open note",
        steps=[
            Step(
                action="click",
                target="text=Grocery list",
                before_state="TextView text='Grocery list'",
                after_state="detail screen",
            ),
            Step(
                action="click",
                target="desc=More options",
                before_state="ImageView desc='More options' clickable=true",
                after_state="menu open",
            ),
            Step(
                action="click",
                target="text=Delete note",
                before_state="TextView text='Delete note'",
                after_state="notes list",
            ),
        ],
    )
    fake_llm.responses = [
        "# delete_opened_note\n\n"
        "**Intent**: Delete the open note via {more_options_label}\n"
        "**Inputs**:\n"
        "- more_options_label (required): the overflow control's label\n"
        "- delete_note_label (required): the delete item's label\n"
        "**Preconditions**: a note is open\n"
        "**Postconditions**: the note is gone\n"
        "**Effects/Outputs**: note deleted\n"
        "**Steps**:\n"
        "1. Tap the note row text='Grocery list'.\n"
        "2. Tap the overflow control desc='{more_options_label}'.\n"
        "3. Tap the menu item text='{delete_note_label}'.\n"
        "**Evidence**: traces t14; 1/1 successes"
    ]
    miner = CardMiner(fake_llm, CardStore(tmp_path))
    card = miner.draft(
        {"start": 0, "end": 2, "name": "delete_opened_note", "intent": ""},
        trace,
    )

    declarations = {item.split()[0]: item for item in card.inputs}
    assert "observed: 'More options'" in declarations["more_options_label"]
    assert "observed: 'Delete note'" in declarations["delete_note_label"]


def test_draft_does_not_read_the_launch_screen_as_build_wording(
    tmp_path, fake_llm
):
    """A value already on the launch screen is this run's data, not a label.

    The note title the trace tapped exists before the function starts, so
    the function must take it as an input rather than record it as the
    build's own wording -- otherwise every run would delete "Grocery list".
    """
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
        "# open_note\n\n**Intent**: open the note {note_title}\n"
        "**Inputs**: note_title (required): the note to open\n"
        "**Preconditions**: on the notes list\n"
        "**Postconditions**: the note is open\n"
        "**Effects/Outputs**: none\n"
        "**Steps**:\n"
        "1. Tap the note row text='{note_title}'.\n"
        "**Evidence**: traces t13; 1/1 successes"
    ]
    miner = CardMiner(fake_llm, CardStore(tmp_path))
    card = miner.draft(
        {"start": 0, "end": 0, "name": "open_note", "intent": ""},
        trace,
    )

    assert len(card.inputs) == 1
    assert "observed" not in card.inputs[0]
    assert "(required)" in card.inputs[0]

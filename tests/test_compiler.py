from specfcg.models import FunctionCard
from specfcg.planner.compiler import StepCompiler


def test_compile_uses_explicit_targets_without_calling_llm(fake_llm):
    card = FunctionCard(
        name="create_note",
        intent="Create a note.",
        inputs=["note_title", "note_content"],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Open the menu via `app:id/fab`.",
            "Select `app:id/note`.",
            "Enter {note_title} into `app:id/title`.",
            "Enter {note_content} into `app:id/content`.",
            "Use back navigation until the list is displayed.",
        ],
    )

    steps = StepCompiler(fake_llm).compile(
        card, {"note_title": "Groceries", "note_content": "Buy milk"}
    )

    assert [
        (step.action, step.target, step.args) for step in steps
    ] == [
        ("click", "resourceId=app:id/fab", ""),
        ("click", "resourceId=app:id/note", ""),
        ("input", "resourceId=app:id/title", "Groceries"),
        ("input", "resourceId=app:id/content", "Buy milk"),
        ("back", "", ""),
    ]


def test_compile_fast_path_extracts_target_from_descriptive_backticks(
    fake_llm,
):
    card = FunctionCard(
        name="open_note_by_title",
        intent="Open a note.",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Tap the title on `TextView resourceId=app:id/note_title`."
        ],
    )

    steps = StepCompiler(fake_llm).compile(card, {})

    assert [(step.action, step.target) for step in steps] == [
        ("click", "resourceId=app:id/note_title")
    ]


def test_compile_fast_path_substitutes_binding_in_text_target(fake_llm):
    card = FunctionCard(
        name="open_note_by_title",
        intent="Open a note.",
        inputs=["note_title"],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=["Tap `text={note_title}` to open the note."],
    )

    steps = StepCompiler(fake_llm).compile(
        card, {"note_title": "Groceries"}
    )

    assert [(step.action, step.target) for step in steps] == [
        ("click", "text=Groceries")
    ]


def test_compile_fast_path_prefers_label_for_bound_click(fake_llm):
    card = FunctionCard(
        name="open_note_by_title",
        intent="Open a note.",
        inputs=["note_title"],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Tap the visible label {note_title} on "
            "`TextView resourceId=app:id/note_title`."
        ],
    )

    steps = StepCompiler(fake_llm).compile(
        card, {"note_title": "Groceries"}
    )

    assert [(step.action, step.target) for step in steps] == [
        ("click", "resourceId=app:id/note_title|text=Groceries")
    ]


def test_compile_fast_path_keeps_button_id_when_other_placeholders_describe_it(
    fake_llm,
):
    card = FunctionCard(
        name="invoke_share_chooser_for_note",
        intent="Share an open note.",
        inputs=["note_title", "note_content", "share_target_label"],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Click `app:id/menu_share` (visible label `共享`) on the "
            "note detail screen for {note_title} containing {note_content}, "
            "so the chooser opens with {share_target_label} available."
        ],
    )

    steps = StepCompiler(fake_llm).compile(
        card,
        {
            "note_title": "Groceries",
            "note_content": "Buy milk",
            "share_target_label": "Gmail",
        },
    )

    assert [(step.action, step.target) for step in steps] == [
        ("click", "resourceId=app:id/menu_share")
    ]


def test_compile_fast_path_parses_quoted_desc_target(fake_llm):
    card = FunctionCard(
        name="archive_note",
        intent="Archive a note.",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=["Click the `ImageView desc='More options'` control."],
    )

    steps = StepCompiler(fake_llm).compile(card, {})

    assert [(step.action, step.target) for step in steps] == [
        ("click", "desc=More options")
    ]


def test_compile_fast_path_parses_quoted_text_target(fake_llm):
    card = FunctionCard(
        name="archive_note",
        intent="Archive a note.",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=["Tap the item labeled `text='Archive'`."],
    )

    steps = StepCompiler(fake_llm).compile(card, {})

    assert [(step.action, step.target) for step in steps] == [
        ("click", "text=Archive")
    ]


def test_compile_fast_path_handles_bare_resource_ids(fake_llm):
    card = FunctionCard(
        name="create_note",
        intent="Create a note.",
        inputs=["note_title"],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Tap it.feio.android.omninotes.foss:id/fab to expand.",
            "Enter {note_title} into the field "
            "it.feio.android.omninotes.foss:id/detail_title.",
        ],
    )

    steps = StepCompiler(fake_llm).compile(
        card, {"note_title": "Groceries"}
    )

    assert [
        (step.action, step.target, step.args) for step in steps
    ] == [
        (
            "click",
            "resourceId=it.feio.android.omninotes.foss:id/fab",
            "",
        ),
        (
            "input",
            "resourceId=it.feio.android.omninotes.foss:id/detail_title",
            "Groceries",
        ),
    ]


def test_compile_fast_path_recognizes_press_back_key_wording(fake_llm):
    card = FunctionCard(
        name="create_note",
        intent="Create a note.",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Press the system Back key once to dismiss the keyboard.",
            "Press the system Back key a second time to return to the list.",
        ],
    )

    steps = StepCompiler(fake_llm).compile(card, {})

    assert [(step.action, step.target) for step in steps] == [
        ("back", ""),
        ("back", ""),
    ]


def test_compile_fast_path_presses_enter_key(fake_llm):
    card = FunctionCard(
        name="search_notes",
        intent="Search notes.",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=["Press Enter to submit the search."],
    )

    steps = StepCompiler(fake_llm).compile(card, {})

    assert [(step.action, step.target, step.args) for step in steps] == [
        ("press", "", "enter")
    ]


def test_compile_fast_path_handles_prefixed_text_targets(fake_llm):
    card = FunctionCard(
        name="save_note",
        intent="Save.",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=["Tap `text=Save`."],
    )

    steps = StepCompiler(fake_llm).compile(card, {})

    assert [(step.action, step.target) for step in steps] == [
        ("click", "text=Save")
    ]


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


def test_compile_strips_markdown_and_quotes_from_targets(
    fake_llm, sample_card
):
    fake_llm.responses = [
        {
            "steps": [
                {
                    "action": "click",
                    "target": "`resourceId=app:id/fab`",
                    "args": "",
                },
                {
                    "action": "click",
                    "target": '"text=Save"',
                    "args": "",
                },
            ]
        }
    ]
    steps = StepCompiler(fake_llm).compile(sample_card, {})
    assert [step.target for step in steps] == [
        "resourceId=app:id/fab",
        "text=Save",
    ]


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

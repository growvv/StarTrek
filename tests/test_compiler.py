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

    # The first press only hides the IME (keycode 111); the second navigates.
    assert [(step.action, step.target) for step in steps] == [
        ("press", ""),
        ("back", ""),
    ]
    assert steps[0].args == "111"


def test_compile_long_press_is_a_held_touch_not_a_key_press(fake_llm):
    """`long_click` exists on the device; the compiler's vocabulary must name
    it, or "Long-press the row" compiles to a keyboard key press."""
    card = FunctionCard(
        name="delete_file",
        intent="Delete a file.",
        inputs=["file_name"],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Long-press the file item labeled {file_name} in "
            "`net.gsantner.markor:id/opoc_filesystem_item__title`."
        ],
    )

    steps = StepCompiler(fake_llm).compile(card, {"file_name": "a.md"})

    assert [(step.action, step.target) for step in steps] == [
        ("long_click", "text=a.md")
    ]


def test_compile_accepts_a_long_click_from_the_compiler_prompt(fake_llm):
    card = FunctionCard(
        name="delete_file",
        intent="Delete a file.",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=["Hold the file row."],
    )
    fake_llm.responses = [
        {
            "steps": [
                {"action": "long_click", "target": "text=a.md", "args": ""}
            ]
        }
    ]

    steps = StepCompiler(fake_llm).compile(card, {})

    assert [(step.action, step.target) for step in steps] == [
        ("long_click", "text=a.md")
    ]


def test_compile_hold_step_targets_the_bound_visible_label(fake_llm):
    """A hold step whose object is named only by its visible label still has
    a concrete target: the label is the bound value."""
    card = FunctionCard(
        name="delete_file",
        intent="Delete a file.",
        inputs=["file_name"],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=["Long-press the file item labeled {file_name}."],
    )

    steps = StepCompiler(fake_llm).compile(card, {"file_name": "a.md"})

    assert [(step.action, step.target) for step in steps] == [
        ("long_click", "text=a.md")
    ]


def test_compile_reads_a_step_that_is_already_an_action(fake_llm):
    """Some cards store the compiled form itself: `long_click text=...`.
    Re-reading the leading verb keeps the gesture instead of downgrading it
    to a tap."""
    card = FunctionCard(
        name="cut_file",
        intent="Cut a file.",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=["long_click text=bench_new.txt"],
    )

    steps = StepCompiler(fake_llm).compile(card, {})

    assert [(step.action, step.target) for step in steps] == [
        ("long_click", "text=bench_new.txt")
    ]


def test_compile_shows_the_model_the_screen_it_targets(fake_llm):
    """A step with no explicit target is grounded in the screen it runs on.
    Without the screen the model invents English labels for a build that
    shows Chinese ones."""
    card = FunctionCard(
        name="open_type",
        intent="Open a type.",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=["Open the type named in the list."],
    )
    fake_llm.responses = [
        {"steps": [{"action": "click", "target": "text=文本注释"}]}
    ]

    steps = StepCompiler(fake_llm).compile(
        card, {}, state="FloatingActionButton text='文本注释'"
    )

    assert "文本注释" in fake_llm.prompts[0]
    assert steps[0].target == "text=文本注释"


def test_compile_tap_on_a_single_quoted_label(fake_llm):
    """Cards quote labels with ' and " interchangeably; both name the same
    visible text."""
    card = FunctionCard(
        name="restore_note",
        intent="Restore a note.",
        inputs=["note_title"],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=["Tap the 'Restore' menu item."],
    )

    steps = StepCompiler(fake_llm).compile(card, {"note_title": "a"})

    assert [(step.action, step.target) for step in steps] == [
        ("click", "text=Restore")
    ]


def test_compile_uses_a_bound_accessible_description(fake_llm):
    """A card can leave the description of a control to its input; the bound
    value is the selector."""
    card = FunctionCard(
        name="navigate_up",
        intent="Go up one folder.",
        inputs=["up_button_description"],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Click the ImageButton whose accessibility description matches "
            "{up_button_description}."
        ],
    )

    steps = StepCompiler(fake_llm).compile(
        card, {"up_button_description": "Go to parent folder"}
    )

    assert [(step.action, step.target) for step in steps] == [
        ("click", "desc=Go to parent folder")
    ]


def test_compile_finds_the_action_verb_after_a_context_clause(fake_llm):
    """Cards often open with where the step happens ("In the tag dialog,
    click ...").  The clause is context; the verb after it is the action."""
    card = FunctionCard(
        name="add_tag",
        intent="Add a tag.",
        inputs=["tag_label"],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "In the tag dialog, click the tag option with visible text "
            "{tag_label}."
        ],
    )

    steps = StepCompiler(fake_llm).compile(card, {"tag_label": "Work"})

    assert [(step.action, step.target) for step in steps] == [
        ("click", "text=Work")
    ]


def test_compile_reads_a_single_quoted_accessible_description(fake_llm):
    card = FunctionCard(
        name="archive_note",
        intent="Archive a note.",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Tap the ImageView with description 'More options' in the note "
            "detail toolbar."
        ],
    )

    steps = StepCompiler(fake_llm).compile(card, {})

    assert [(step.action, step.target) for step in steps] == [
        ("click", "desc=More options")
    ]


def test_compile_press_of_a_named_key_is_a_key_press(fake_llm):
    """`press` accepts hardware key names.  A step that says which key to
    press is a press, not a tap on whatever id it mentions."""
    card = FunctionCard(
        name="dismiss_keyboard",
        intent="Dismiss the keyboard.",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Press the Escape key.",
            "Press the Home key to leave the app.",
        ],
    )

    steps = StepCompiler(fake_llm).compile(card, {})

    assert [(step.action, step.target, step.args) for step in steps] == [
        ("press", "", "escape"),
        ("press", "", "home"),
    ]


def test_compile_tap_on_a_quoted_label_targets_the_label(fake_llm):
    """A step can name its control only by the label the user sees.  The
    label is a concrete selector; refusing it sends the whole card to the
    LLM for a control the card already described."""
    card = FunctionCard(
        name="move_file",
        intent="Move a file.",
        inputs=["file_name"],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Tap the \"More options\" overflow ImageView in the selection "
            "toolbar.",
            "Tap the \"Move\" menu item.",
        ],
    )

    steps = StepCompiler(fake_llm).compile(
        card, {"file_name": "a.md"}
    )

    assert [(step.action, step.target) for step in steps] == [
        ("click", "text=More options"),
        ("click", "text=Move"),
    ]


def test_compile_identifies_a_row_by_the_title_it_displays(fake_llm):
    """A container named by a descendant's visible title must be addressed by
    that title.  The container id alone matches whichever row is first."""
    card = FunctionCard(
        name="open_markdown_file",
        intent="Open a document.",
        inputs=["document_name"],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Tap the clickable file item container LinearLayout "
            "id='net.gsantner.markor:id/opoc_filesystem_item__root' whose "
            "visible title TextView id='net.gsantner.markor:id/"
            "opoc_filesystem_item__title' displays {document_name}."
        ],
    )

    steps = StepCompiler(fake_llm).compile(
        card, {"document_name": "bench_edit.md"}
    )

    assert [(step.action, step.target) for step in steps] == [
        ("click", "text=bench_edit.md")
    ]


def test_compile_filters_a_shared_menu_id_by_its_visible_label(fake_llm):
    """Two menu items share one id; the label tells them apart.

    ``android:id/title`` is the text view of every menu row, so the id alone
    selects whichever row comes first.  The visible text is what
    distinguishes them, and the id still scopes the query.
    """
    card = FunctionCard(
        name="rename_file",
        intent="Rename a file.",
        inputs=["current_name", "new_name"],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Tap the menu item TextView with id='android:id/title' and "
            "visible text 'Rename'."
        ],
    )

    steps = StepCompiler(fake_llm).compile(
        card, {"current_name": "a.txt", "new_name": "b.txt"}
    )

    assert [(step.action, step.target) for step in steps] == [
        ("click", "resourceId=android:id/title|text=Rename")
    ]


def test_compile_typing_step_targets_the_field_not_the_dialog_title(fake_llm):
    """A typing step names the dialog it is in and the field it types into.
    The field is the target; the dialog title is context."""
    card = FunctionCard(
        name="rename_file",
        intent="Rename a file.",
        inputs=["current_name", "new_name"],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "In the dialog titled TextView id='com.amaze.filemanager:id/md_title' "
            "with visible text 'Rename', replace the text in EditText "
            "id='com.amaze.filemanager:id/singleedittext_input' with "
            "{new_name}."
        ],
    )

    steps = StepCompiler(fake_llm).compile(
        card, {"current_name": "a.txt", "new_name": "b.txt"}
    )

    assert [
        (step.action, step.target, step.args) for step in steps
    ] == [
        (
            "input",
            "resourceId=com.amaze.filemanager:id/singleedittext_input",
            "b.txt",
        )
    ]


def test_compile_back_step_treats_the_named_widget_as_context(fake_llm):
    """The verb is the action; the widget a Back step names is the screen it
    leaves, not something to tap.  Clicking the title field instead of going
    back leaves the app on the detail screen and every later step misses."""
    card = FunctionCard(
        name="return_to_notes_list",
        intent="Return to the notes list.",
        inputs=["note_title"],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Press the system Back button once from the note detail screen "
            "for {note_title}, shown by EditText "
            "id='it.feio.android.omninotes.foss:id/detail_title'."
        ],
    )

    steps = StepCompiler(fake_llm).compile(
        card, {"note_title": "Project Alpha"}
    )

    assert [(step.action, step.target) for step in steps] == [("back", "")]


def test_compile_enter_step_presses_the_key_not_the_field(fake_llm):
    card = FunctionCard(
        name="search_notes",
        intent="Search notes.",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Press Enter in the search field "
            "`it.feio.android.omninotes.foss:id/search_src_text` to submit "
            "the query."
        ],
    )

    steps = StepCompiler(fake_llm).compile(card, {})

    assert [(step.action, step.target, step.args) for step in steps] == [
        ("press", "", "enter")
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


def test_compile_skips_a_verification_step(fake_llm):
    """A probe plan's "Confirm X is visible" is not an action.

    Compiled as a click it taps a control the screen does not have, and the
    probe aborts on a selector that was never meant to be pressed.
    """
    card = FunctionCard(
        name="create_checklist_note",
        intent="Create a checklist note.",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Tap 'app:id/fab_expand_menu_button'",
            "Confirm 'app:id/fab_add_checklist' is visible",
            "Tap 'app:id/fab_add_checklist'",
        ],
    )

    steps = StepCompiler(fake_llm).compile(card, {})

    assert [(step.action, step.target) for step in steps] == [
        ("click", "resourceId=app:id/fab_expand_menu_button"),
        ("click", "resourceId=app:id/fab_add_checklist"),
    ]


def test_compile_scopes_a_row_button_to_the_row_the_step_names(fake_llm):
    """A control that repeats on every row cannot be named by its id alone.

    Amaze's properties button has the same id on all eight rows.  The step
    says which row it means ("in the row for {current_name}"); dropping that
    scopes the tap to whichever row is first, so the plan renames the wrong
    file and the goal's file is left untouched.
    """
    card = FunctionCard(
        name="rename_file_via_row_menu",
        intent="Rename {current_name} to {new_name}.",
        inputs=["current_name", "new_name"],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Tap the ImageButton with content description 'Properties' and "
            "id='app:id/properties' in the row for {current_name}."
        ],
    )

    steps = StepCompiler(fake_llm).compile(
        card,
        {"current_name": "bench_old.txt", "new_name": "bench_renamed.txt"},
    )

    assert [(step.action, step.target) for step in steps] == [
        ("click", "within=text=bench_old.txt|resourceId=app:id/properties")
    ]


def test_compile_row_scope_uses_a_quoted_label_too(fake_llm):
    card = FunctionCard(
        name="open_row_menu",
        intent="Open the row menu.",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Tap the ImageButton id='app:id/properties' in the row "
            "titled 'bench_pack'."
        ],
    )

    steps = StepCompiler(fake_llm).compile(card, {})

    assert [(step.action, step.target) for step in steps] == [
        ("click", "within=text=bench_pack|resourceId=app:id/properties")
    ]


def test_compile_substitutes_a_bound_accessible_description(fake_llm):
    """A bound value must be substituted wherever the target came from.

    The diary's drawer toggle is named only by its accessibility description,
    which the card writes as a placeholder in backticks.  Emitting
    ``desc={open_navigation_label}`` sends a literal brace string to the
    device, so the step fails and the whole plan dies on step two.
    """
    card = FunctionCard(
        name="open_statistics",
        intent="Open statistics.",
        inputs=["open_navigation_label", "statistics_menu_label"],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Click the navigation drawer toggle `ImageButton` with "
            "accessibility description `{open_navigation_label}`."
        ],
    )

    steps = StepCompiler(fake_llm).compile(
        card,
        {
            "open_navigation_label": "Open navigation",
            "statistics_menu_label": "Statistics",
        },
    )

    assert [(step.action, step.target) for step in steps] == [
        ("click", "desc=Open navigation")
    ]


def test_compile_tells_the_model_a_row_below_the_fold_is_still_reachable(
    fake_llm,
):
    """A list hides its later rows, but the device scrolls to them.

    Without that fact the model reads a short screen as a complete one and
    replaces the step with a different route it invents (Amaze: "switch to
    grid view so the file becomes visible"), which the graph never
    authorised and the oracle does not reward.
    """
    card = FunctionCard(
        name="rename_file",
        intent="Rename a file.",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=["Open the row menu for the file named in the goal."],
    )
    fake_llm.responses = [
        {"steps": [{"action": "click", "target": "text=bench_old.txt"}]}
    ]

    StepCompiler(fake_llm).compile(
        card, {}, state="RecyclerView id='app:id/list' scrollable=true"
    )

    prompt = fake_llm.prompts[0]
    assert "below the fold" in prompt
    assert "scrolls" in prompt


def test_compile_dismisses_the_keyboard_without_leaving_the_screen(fake_llm):
    """Hiding the soft keyboard is not navigation.

    A card that says "Press Android Back to dismiss the soft keyboard" is
    describing how to get a keyboard out of the way.  Compiled as a plain
    ``back`` it navigates when no keyboard is up -- and in a cleared app the
    keyboard is not up, so the step leaves the screen the next step needs
    and every later action misses.  The device dismisses the IME by keycode
    (ESCAPE, 111) without navigating.
    """
    card = FunctionCard(
        name="return_to_file_list",
        intent="Return to the file list.",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Press Android Back to dismiss the soft keyboard while the "
            "document editor is active.",
            "Press Android Back again from the document toolbar.",
        ],
    )

    steps = StepCompiler(fake_llm).compile(card, {})

    assert [(step.action, step.target, step.args) for step in steps] == [
        ("press", "", "111"),
        ("back", "", ""),
    ]


def test_compile_keeps_a_back_step_that_only_mentions_the_keyboard(
    fake_llm,
):
    """A step that navigates *away from* the keyboard is still navigation."""
    card = FunctionCard(
        name="leave_search",
        intent="Leave the search screen.",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=["Press Back to close the search results and return to the list."],
    )

    steps = StepCompiler(fake_llm).compile(card, {})

    assert [(step.action, step.target) for step in steps] == [("back", "")]


def test_compile_tells_apart_rows_that_share_an_id_by_their_code_label(
    fake_llm,
):
    """A menu row's id repeats on every row; its label is the selector.

    ``net.gsantner.markor:id/title`` is the text view of every item in the
    selection overflow menu.  A step that names the control as "the `复制`
    (Copy) menu item (TextView id ...)" therefore has to keep the label as a
    filter: the bare id clicks whichever row comes first, which is Sort, not
    Copy -- and the copy destination picker never opens.
    """
    card = FunctionCard(
        name="copy_file_to_folder",
        intent="Copy a file into a folder.",
        inputs=["source_file_name", "destination_folder_name"],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Long-click the file item whose visible title is "
            "{source_file_name} to enter selection mode.",
            "Tap the `更多选项` (More options) button (ImageView desc "
            "`更多选项`) in the selection toolbar.",
            "Tap the `复制` (Copy) menu item (TextView id "
            "`net.gsantner.markor:id/title`) to open the copy destination "
            "folder picker.",
        ],
    )

    steps = StepCompiler(fake_llm).compile(
        card,
        {"source_file_name": "bench_move.md",
         "destination_folder_name": "bench_dest"},
    )

    assert (steps[2].action, steps[2].target) == (
        "click",
        "resourceId=net.gsantner.markor:id/title|text=复制",
    )


def test_compile_keeps_the_id_scope_when_the_label_is_on_a_child_node(
    fake_llm,
):
    """The id scopes the query; the label picks the control inside it.

    A row's id is on the container and the label the user reads is on a
    child TextView (``LinearLayout id=...:id/menu_new_file`` holding
    ``text='文件'``).  Dropping the id would also match the list's "文件"
    section header, so the id stays as the scope and the device resolves
    the label on the node or inside it.
    """
    card = FunctionCard(
        name="create_new_empty_file",
        intent="Create a new empty file.",
        inputs=["file_name"],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Tap the floating action button with resource id "
            "`com.amaze.filemanager:id/sd_main_fab` to open the create menu.",
            "Tap the menu item labeled `文件` with resource id "
            "`com.amaze.filemanager:id/menu_new_file` to choose new file.",
        ],
    )

    steps = StepCompiler(fake_llm).compile(card, {"file_name": "bench_new.txt"})

    assert (steps[1].action, steps[1].target) == (
        "click",
        "resourceId=com.amaze.filemanager:id/menu_new_file|text=文件",
    )


def test_compile_keeps_the_id_scope_for_a_menu_item(fake_llm):
    """The id scopes; the label selects inside it.

    The same rule as the child-node case, stated on a menu row: the id is
    never dropped just because the label is what the user reads.
    """
    card = FunctionCard(
        name="create_new_empty_file",
        intent="Create a new empty file.",
        inputs=["file_name"],
        preconditions="",
        postconditions="",
        effects_outputs="",
        steps=[
            "Tap the menu item labeled `文件` with resource id "
            "`com.amaze.filemanager:id/menu_new_file` to choose new file.",
        ],
    )

    steps = StepCompiler(fake_llm).compile(card, {"file_name": "bench_new.txt"})

    assert (steps[0].action, steps[0].target) == (
        "click",
        "resourceId=com.amaze.filemanager:id/menu_new_file|text=文件",
    )

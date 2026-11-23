from __future__ import annotations

from pathlib import Path

from specfcg.scoring.coverage_eval import (
    FunctionSpec,
    graph_coverage,
    load_inventory,
    observed_coverage,
    path_confidence,
)
from specfcg.models import Edge, FunctionCard, Graph


def _card(name: str, success: int = 1, attempts: int = 1) -> FunctionCard:
    return FunctionCard(
        name=name,
        intent=f"intent {name}",
        inputs=[],
        preconditions="",
        postconditions="",
        effects_outputs="",

        success_count=success,
        attempt_count=attempts,
    )


INVENTORY = """
app: omninotes
functions:
  - id: create_note
    label: Create a note
    source: src/main/java/.../MainActivity.java#onOptionsItemSelected
    cards: [create_note]
    ui_evidence: [笔记, note]
  - id: search_notes
    label: Search notes
    source: res/menu/menu_main.xml#search
    cards: [search_notes_by_keyword]
    ui_evidence: [搜索]
  - id: archive_note
    label: Archive a note
    source: res/menu/menu_detail.xml#archive
    cards: [archive_note]
    ui_evidence: [归档, archive]
"""


def test_load_inventory(tmp_path):
    path = tmp_path / "omninotes.yaml"
    path.write_text(INVENTORY, encoding="utf-8")
    functions = load_inventory(path)
    assert [f.id for f in functions] == [
        "create_note",
        "search_notes",
        "archive_note",
    ]
    assert functions[0].cards == ["create_note"]


def test_graph_coverage_counts_cards_present():
    graph = Graph(cards={"create_note": _card("create_note")})
    functions = [
        FunctionSpec(
            id="create_note", label="Create", cards=["create_note"]
        ),
        FunctionSpec(
            id="search", label="Search", cards=["search_notes_by_keyword"]
        ),
    ]
    report = graph_coverage(functions, graph)
    assert report.total == 2
    assert report.covered == 1
    assert report.score == 0.5
    assert report.missing == ["search"]


def test_graph_coverage_matches_cards_by_name_tokens():
    graph = Graph(
        cards={
            "stop_current_activity": _card("stop_current_activity"),
            "open_statistics_screen": _card("open_statistics_screen"),
            "open_settings": _card("open_settings"),
        }
    )
    functions = [
        FunctionSpec(id="stop_activity", label="Stop the activity"),
        FunctionSpec(id="open_statistics", label="Open statistics"),
        FunctionSpec(id="open_map", label="Open the map"),
    ]
    report = graph_coverage(functions, graph)

    assert report.hits["stop_activity"] == "stop_current_activity"
    assert report.hits["open_statistics"] == "open_statistics_screen"
    assert report.missing == ["open_map"]


def test_graph_coverage_matches_expected_card_names_by_tokens():
    graph = Graph(
        cards={"create_activity_type": _card("create_activity_type")}
    )
    functions = [
        FunctionSpec(
            id="add_activity_type",
            label="Create an activity type",
            cards=["add_activity_type"],
        )
    ]
    report = graph_coverage(functions, graph)
    assert report.hits["add_activity_type"] == "create_activity_type"


def test_graph_coverage_matches_cards_with_descriptive_suffixes():
    graph = Graph(
        cards={
            "share_note_via_system_chooser": _card(
                "share_note_via_system_chooser"
            ),
            "sort_notes_by_title": _card("sort_notes_by_title"),
        }
    )
    functions = [
        FunctionSpec(id="share_note", label="Share a note"),
        FunctionSpec(id="sort_notes", label="Sort the notes"),
    ]
    report = graph_coverage(functions, graph)

    assert report.hits["share_note"] == "share_note_via_system_chooser"
    assert report.hits["sort_notes"] == "sort_notes_by_title"
    assert report.missing == []


def test_graph_coverage_matches_a_single_distinctive_verb():
    graph = Graph(cards={"sort_file_list": _card("sort_file_list")})
    functions = [FunctionSpec(id="sort", label="Sort the file list")]
    report = graph_coverage(functions, graph)
    assert report.hits["sort"] == "sort_file_list"


def test_graph_coverage_does_not_match_a_different_verb():
    graph = Graph(cards={"delete_opened_note": _card("delete_opened_note")})
    functions = [FunctionSpec(id="edit_note", label="Edit a note")]
    assert graph_coverage(functions, graph).covered == 0


def test_graph_coverage_does_not_match_shared_generic_verbs():
    graph = Graph(cards={"open_settings": _card("open_settings")})
    functions = [FunctionSpec(id="open_map", label="Open the map")]
    assert graph_coverage(functions, graph).covered == 0


def test_observed_coverage_matches_ui_evidence():
    functions = [
        FunctionSpec(
            id="create", label="Create", ui_evidence=["笔记", "新建"]
        ),
        FunctionSpec(
            id="sort", label="Sort", ui_evidence=["排序"]
        ),
    ]
    report = observed_coverage(functions, "我的笔记\n新建笔记")
    assert report.covered == 1
    assert report.missing == ["sort"]


def test_path_confidence_uses_card_rates_and_length():
    graph = Graph(
        cards={
            "a": _card("a", success=8, attempts=10),
            "b": _card("b", success=1, attempts=1),
        },
        edges=[
            Edge(from_card="a", to_card="b", type="sequence"),
        ],
    )
    # min(smoothed rate) * 0.9 for the one extra card:
    # a = (8+1)/(10+2) = 0.75, b = (1+1)/(1+2) = 0.667
    assert round(path_confidence(graph, ["a", "b"]), 3) == 0.6
    assert path_confidence(graph, []) == 0.0
    assert path_confidence(graph, ["missing"]) == 0.0


def test_path_confidence_does_not_read_one_success_as_certainty():
    """A card seen once must not score 1.00.

    Almost every mined card is 1/1, so ``success/attempt`` made every path
    score 1.0 and every probe predict the same confidence.  Smoothing keeps
    one observation strong evidence without turning it into proof.
    """
    graph = Graph(cards={"a": _card("a", success=1, attempts=1)})

    assert path_confidence(graph, ["a"]) < 1.0
    assert path_confidence(graph, ["a"]) > 0.5


def test_path_confidence_penalizes_long_paths():
    graph = Graph(
        cards={
            "a": _card("a"),
            "b": _card("b"),
            "c": _card("c"),
        }
    )
    assert path_confidence(graph, ["a", "b"]) > path_confidence(
        graph, ["a", "b", "c"]
    )


INVENTORY_WITH_UNREACHABLE = """
app: activitydiary
functions:
  - id: start_activity
    label: Start recording
    cards: [start_activity]
  - id: attach_picture
    label: Attach a picture
    cards: [attach_picture]
    reachable: false
    note: fab_attach_picture opens no picker on Android 16
"""


def test_load_inventory_reads_the_reachable_flag(tmp_path):
    path = tmp_path / "diary.yaml"
    path.write_text(INVENTORY_WITH_UNREACHABLE, encoding="utf-8")
    functions = load_inventory(path)

    assert functions[0].reachable is True
    assert functions[1].reachable is False


def test_graph_coverage_scores_only_reachable_functions():
    graph = Graph(cards={"start_activity": _card("start_activity")})
    functions = [
        FunctionSpec(id="start_activity", label="Start"),
        FunctionSpec(
            id="attach_picture", label="Attach a picture", reachable=False
        ),
    ]

    report = graph_coverage(functions, graph)

    assert report.total == 1
    assert report.covered == 1
    assert report.score == 1.0
    assert report.missing == []
    assert report.unreachable == ["attach_picture"]


def test_graph_coverage_gives_each_card_to_one_function():
    """create_note must not be satisfied by create_checklist_note.

    Both names contain {create, note}; the checklist card is the one
    create_checklist needs, so create_note has to take the text card.
    """
    graph = Graph(
        cards={
            "create_text_note": _card("create_text_note"),
            "create_checklist_note": _card("create_checklist_note"),
        }
    )
    functions = [
        FunctionSpec(id="create_note", label="Create a text note"),
        FunctionSpec(
            id="create_checklist", label="Create a checklist note"
        ),
    ]

    report = graph_coverage(functions, graph)

    assert report.hits["create_note"] == "create_text_note"
    assert report.hits["create_checklist"] == "create_checklist_note"


def test_graph_coverage_matches_plural_and_past_forms():
    graph = Graph(
        cards={"open_archived_notes": _card("open_archived_notes")}
    )
    functions = [
        FunctionSpec(
            id="open_archive_view", label="Open the archived-notes view"
        )
    ]

    report = graph_coverage(functions, graph)

    assert report.hits["open_archive_view"] == "open_archived_notes"


def test_graph_coverage_matches_unarchive_to_restore():
    graph = Graph(
        cards={"restore_archived_note": _card("restore_archived_note")}
    )
    functions = [
        FunctionSpec(
            id="unarchive_note", label="Restore a note from the archive"
        )
    ]

    report = graph_coverage(functions, graph)

    assert report.hits["unarchive_note"] == "restore_archived_note"


def test_graph_coverage_matches_set_to_assign():
    graph = Graph(
        cards={
            "create_and_assign_category": _card(
                "create_and_assign_category"
            )
        }
    )
    functions = [
        FunctionSpec(id="set_category", label="Assign a category")
    ]

    report = graph_coverage(functions, graph)

    assert report.hits["set_category"] == "create_and_assign_category"


def test_graph_coverage_reads_the_leading_verb_as_the_action():
    """delete_opened_note is the delete card, not an open card.

    "opened" describes which note, so an extra verb in the card name must not
    disqualify it when both names act on the same verb.  open_note still must
    not claim that card: its verb is open, the card's action is delete.
    """
    graph = Graph(cards={"delete_opened_note": _card("delete_opened_note")})
    functions = [
        FunctionSpec(id="delete_note", label="Delete a note"),
        FunctionSpec(id="open_note", label="Open a note"),
    ]

    report = graph_coverage(functions, graph)

    assert report.hits == {"delete_note": "delete_opened_note"}
    assert report.missing == ["open_note"]


def test_coverage_does_not_score_the_card_names_written_from_the_graph():
    """The hint field is an answer key, not evidence.

    ``cards:`` names the card that implemented a function *in one particular
    build*.  Scoring another build against it measures whether the two builds
    agreed on a name, which is not whether either can perform the function:
    the inventory written against the recorded activitydiary graph matched it
    15/15 while a fresh build of the same traces -- which never saw the
    inventory -- matched 13/15, purely because two cards were named
    differently.  The function here is called ``edit_diary_entry``; the hint
    says ``edit_diary_note``; the card is called ``edit_note``.
    """
    graph = Graph(cards={"edit_diary_note": _card("edit_diary_note")})
    functions = [
        FunctionSpec(
            id="edit_diary_entry",
            label="Edit a recorded diary entry",
            cards=["edit_diary_note"],
        )
    ]

    report = graph_coverage(functions, graph)

    assert report.covered == 0
    assert report.missing == ["edit_diary_entry"]


def test_hint_dependence_reports_what_the_hints_would_have_added():
    """The leak is measured, not hidden: report how much the hints inflate.

    Dropping the hints from the score is only half the fix.  A reader
    comparing this build with the one the inventory was written against needs
    to see how much of that older number was the hint field agreeing with
    itself.
    """
    graph = Graph(cards={"edit_note": _card("edit_note")})
    functions = [
        FunctionSpec(
            id="edit_diary_entry",
            label="Edit a recorded diary entry",
            cards=["edit_note"],
        )
    ]

    report = graph_coverage(functions, graph)

    assert report.covered == 0
    assert report.hint_dependence == 1.0

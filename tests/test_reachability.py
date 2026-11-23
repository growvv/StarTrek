"""Reaching the buggy screen is a question the UI can answer.

The crash experiment's oracle is high-variance: the agent must finish the
whole walk *and* hit the exact state that crashes. When the executor cannot
finish, both arms read zero and the comparison says nothing. This one asks
the method's own question — did the description get the agent to the right
screen — and answers it from the final UI dump.
"""
from __future__ import annotations

from specfcg.benchmark.reachability import (
    TARGET_BY_CLASS,
    TargetScreen,
    reached,
    summarise,
    target_for,
)


def test_a_file_info_dialog_is_recognised_by_its_widget_id():
    """The id survives a locale change; this device runs an English build."""
    ui = (
        "TextView text='Name' id='net.gsantner.markor:id/"
        "ui__fileinfodialog__description'"
    )
    target = target_for(["net.gsantner.markor.ui.FileInfoDialog.setUpDialog"])

    assert target is not None
    assert target.name == "file info dialog"
    assert reached(ui, target).reached is True


def test_being_elsewhere_in_the_same_app_is_not_reaching_it():
    """The distinction the whole measurement rests on."""
    ui = "TextView text='Notebook' id='net.gsantner.markor:id/largeLabel'"
    target = TARGET_BY_CLASS["FileInfoDialog"]

    result = reached(ui, target)

    assert result.reached is False
    assert result.missing == list(target.markers)


def test_a_delete_confirmation_counts_whichever_dialog_vocabulary_it_uses():
    """Amaze uses a Material dialog; the platform one is also a delete flow."""
    target = TARGET_BY_CLASS["DeleteTask"]
    material = (
        "TextView text='DELETE' id='com.amaze.filemanager:id/"
        "md_buttonDefaultPositive'"
    )

    assert reached(material, target).reached is True


def test_a_background_task_maps_to_the_screen_a_user_reaches_it_from():
    """DeleteTask draws nothing itself; the confirmation dialog is the gate.

    Reaching that dialog is the observable that says the agent is about to
    run the code that crashes, without needing the crash to happen.
    """
    target = target_for(["com.amaze.asynctasks.DeleteTask.onPostExecute"])

    assert target is not None
    assert target.name == "delete confirmation"


def test_a_platform_only_stack_has_no_target():
    assert target_for(["java.util.ArrayList.get", "android.os.Handler.dispatchMessage"]) is None


def test_the_summary_reports_a_rate_and_a_breakdown_per_target():
    results = [
        reached("x fileinfodialog y", TARGET_BY_CLASS["FileInfoDialog"]),
        reached("nothing here", TARGET_BY_CLASS["FileInfoDialog"]),
        reached("md_buttonDefaultPositive", TARGET_BY_CLASS["DeleteTask"]),
    ]

    summary = summarise(results)

    assert summary["runs"] == 3
    assert summary["reached"] == 2
    assert summary["targets"]["file info dialog"] == {"runs": 2, "reached": 1}


def test_an_empty_run_set_does_not_divide_by_zero():
    assert summarise([])["rate"] == 0.0


def test_every_action_target_has_a_screen_or_is_declared_absent():
    """A target list that silently misses a class would hide runs."""
    from specfcg.datasets.bug_task import ACTION_BY_CLASS

    covered = set(TARGET_BY_CLASS)
    absent_by_design = {
        "CopyTask",
        "MoveTask",
        "ExtractTask",
        "Reviewer",
        "Gallery",
        "Settings",
        "Search",
        "HistoryRecyclerViewAdapter",
        "FavoritesWriter",
        "BookmarkControl",
        "BookmarkDBAdapter",
    }

    assert set(ACTION_BY_CLASS) == covered | absent_by_design

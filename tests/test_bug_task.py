"""A crash's stack names the action that reaches it."""
from __future__ import annotations

from specfcg.benchmark.bug_task import (
    ACTION_BY_CLASS,
    action_from_frames,
    app_frames,
    coverage,
    task_for,
)
from specfcg.benchmark.themis import BuggyVersion, CrashSignature


def _version(*frames: str, goal: str = "") -> BuggyVersion:
    return BuggyVersion(
        app="com.example",
        directory="Example-1.0-#1",
        package="com.example",
        crashes=[
            CrashSignature(
                exception="java.lang.NullPointerException",
                frames=list(frames),
                process="com.example",
            )
        ],
    )


def test_platform_frames_are_not_the_app():
    frames = [
        "java.util.ArrayList.get(ArrayList.java:411)",
        "com.example.app.Foo.bar(Foo.java:42)",
        "android.os.Handler.dispatchMessage(Handler.java:102)",
    ]
    assert app_frames(frames) == ["com.example.app.Foo.bar(Foo.java:42)"]


def test_a_delete_crash_asks_for_a_delete():
    """The dataset's page description cannot delete, so it cannot crash here.

    Amaze 3.3.2 dies in `DeleteTask.onPostExecute`; a task that only looks at
    the navigation menu never runs that code.
    """
    version = _version(
        "java.util.ArrayList.get(ArrayList.java:411)",
        "com.amaze.filemanager.asynchronous.asynctasks.DeleteTask.onPostExecute(DeleteTask.java:175)",
    )

    task = task_for(version, goal="The current page is a navigation menu")

    assert task is not None
    assert "delete" in task.text.lower()
    assert task.source == "crash stack"


def test_a_browser_crash_asks_for_the_browser():
    version = _version(
        "com.ichi2.anki.CardBrowser$20.onPostExecute(CardBrowser.java:1364)",
    )
    task = task_for(version, goal="Manage flashcard decks in AnkiDroid")
    assert "card browser" in task.text.lower()


def test_an_unknown_stack_falls_back_to_a_goal_that_is_an_action():
    version = _version("com.example.UnknownWidget.update(UnknownWidget.java:10)")
    task = task_for(version, goal="Delete the file named notes.txt")
    assert task is not None
    assert task.source == "dataset goal"


def test_a_page_description_is_not_accepted_as_a_task():
    """Acting on a page description cannot reach a crash in another task."""
    version = _version("com.example.UnknownWidget.update(UnknownWidget.java:10)")
    assert task_for(version, goal="The current page is a navigation menu") is None


def test_a_version_with_no_task_is_reported_not_invented():
    version = _version("com.example.UnknownWidget.update(UnknownWidget.java:10)")
    summary = coverage([version])
    assert summary["derivable"] == 0
    assert summary["underivable_ids"] == ["Example-1.0-#1"]


def test_every_mapped_class_produces_a_usable_task():
    for fragment in ACTION_BY_CLASS:
        version = _version(f"com.example.{fragment}Worker.run(Worker.java:1)")
        task = task_for(version)
        assert task is not None, fragment
        assert task.text.startswith("In the app,"), fragment
        assert task.text.endswith("on screen."), fragment

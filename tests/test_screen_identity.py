"""The agent has to know which screen it is looking at."""
from __future__ import annotations

from mobile_agent.screen import changed, describe, screen_identity


def test_a_file_editor_is_not_a_file_list():
    """Markor 0.3.9: tapping the row opened the editor, and the agent kept
    looking for the file-info action there for fourteen steps."""
    editor = (
        "EditText id='net.gsantner.markor:id/"
        "document__fragment__edit__highlighting_editor'"
    )
    listing = "TextView id='net.gsantner.markor:id/note_title' text='Readme'"

    assert screen_identity(editor) == "file editor (MainActivity)" or screen_identity(editor).startswith("file editor")
    assert screen_identity(listing).startswith("file list")
    assert changed(screen_identity(editor), screen_identity(listing))


def test_the_activity_distinguishes_two_screens_with_the_same_controls():
    ui = "TextView id='app:id/note_title'"
    assert screen_identity(ui, "app.MainActivity") != screen_identity(ui, "app.FolderActivity")


def test_an_unknown_screen_still_gets_a_name():
    assert screen_identity("nothing familiar", "app.MainActivity") == "unknown (MainActivity)"
    assert screen_identity("", "") == "unknown"


def test_the_observation_says_when_nothing_moved():
    """An action that changes nothing is the signal to try something else."""
    assert "unchanged" in describe("file list (Main)", "file list (Main)")
    assert "changed from" in describe("file editor (Main)", "file list (Main)")
    assert describe("file list (Main)") == "Current screen: file list (Main)"


def test_an_open_confirmation_dialog_is_visible_in_the_ui():
    """Amaze's delete ended on the confirmation dialog and the agent stopped.

    The file was never removed; the run reported a deletion that did not
    happen. The platform's positive button is `android:id/button1`.
    """
    from mobile_agent.screen import pending_confirmation

    platform = "Button text='OK' id='android:id/button1' clickable=true"
    material = (
        "TextView text='DELETE' "
        "id='com.amaze.filemanager:id/md_buttonDefaultPositive' clickable=true"
    )
    assert pending_confirmation(platform) is True
    assert pending_confirmation(material) is True
    assert pending_confirmation("TextView text='Documents'") is False
    assert pending_confirmation("") is False

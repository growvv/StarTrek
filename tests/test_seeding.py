"""A file task starts from a file, and the build's path is not guessable."""
from __future__ import annotations

from specfcg.android.seeding import as_record, prepare, seed_for


class FakeDevice:
    def __init__(self, lists: bool = True) -> None:
        self.calls: list[str] = []
        self.lists = lists

    def shell(self, command: str) -> str:
        self.calls.append(command)
        if command.startswith("ls "):
            return "sample.txt" if self.lists else ""
        return ""


def test_markors_notebook_path_is_the_one_its_own_preferences_name():
    """The 2018 build reads Documents/markor, not a directory called Notebook.

    Seeding the wrong path left the app showing "This directory is empty"
    while the file sat on disk, so the run measured an empty list.
    """
    spec = seed_for("net.gsantner.markor")
    assert spec is not None
    assert spec.directory == "/storage/emulated/0/Documents/markor"


def test_seeding_creates_the_directory_and_makes_the_file_readable():
    """A file written by the adb shell is owned by root on older builds."""
    device = FakeDevice()

    reason = prepare(device, "net.gsantner.markor")

    assert reason == ""
    joined = " | ".join(device.calls)
    assert "mkdir -p /storage/emulated/0/Documents/markor" in joined
    assert "chmod 664" in joined


def test_a_seed_that_does_not_show_up_is_reported():
    device = FakeDevice(lists=False)

    reason = prepare(device, "net.gsantner.markor")

    assert "does not list it" in reason


def test_an_unknown_build_is_not_given_a_guessed_path():
    """A default path would measure the default, not the build."""
    device = FakeDevice()

    reason = prepare(device, "com.example.unknown")

    assert "no known data path" in reason
    assert device.calls == []


def test_the_record_says_whether_a_seed_was_used():
    assert as_record("net.gsantner.markor")["seeded"] is True
    assert as_record("com.example.unknown")["seeded"] is False


def test_a_single_item_directory_is_left_with_only_the_sample():
    """Amaze's delete crash needs a directory that held exactly one item.

    `DeleteTask.onPostExecute` indexes row 0 of an adapter whose list just
    became empty; with other files present the list is never empty.
    """
    device = FakeDevice()

    reason = prepare(device, "com.amaze.filemanager")

    assert reason == ""
    joined = " | ".join(device.calls)
    assert "! -name 'sample.txt' -exec rm -rf" in joined

"""Did the agent reach the screen where the buggy code runs?

The crash-detection experiment asks a hard question — did the app crash — and
answers it with a high-variance, downstream signal: the agent has to walk a
multi-step path *and* land on the exact state that triggers the bug.  When the
executor cannot finish the walk, both arms of a comparison sit at zero and the
number says nothing about the method.

This module asks the question one step earlier, and it is the question the
method actually claims to improve: did the agent get to the screen the crash
happens on?  `FileInfoDialog` is reached when a dialog with that class's
widgets is on screen; `DeleteTask` when the delete confirmation is showing.
That is observable from the UI dump, needs no crash, and needs no
archaeology into the app's source.

The markers are the widget ids the crashing class renders.  A class that
renders nothing nameable — a background `AsyncTask` — has no target here and
is reported as such rather than given a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TargetScreen:
    """The screen a crashing class puts on the device."""

    name: str
    # Substrings that must all appear in the UI text.  A widget id is
    # preferred over visible text: the id survives a locale change, and this
    # device runs an English build while the dataset's traces were Chinese.
    markers: tuple[str, ...]
    # What the agent is asked to do to get here.
    action: str
    matched_class: str = ""


@dataclass
class ReachResult:
    """Whether one run reached its target screen."""

    version: str
    target: str
    reached: bool = False
    markers_seen: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def as_record(self) -> dict:
        return {
            "version": self.version,
            "target": self.target,
            "reached": self.reached,
            "markers_seen": self.markers_seen,
            "missing": self.missing,
        }


# The screen each crash site renders, keyed by the same class fragments
# `bug_task.ACTION_BY_CLASS` uses.  Only classes that draw something nameable
# appear: `DeleteTask` is a background task, and the screen a user reaches it
# from is the delete confirmation dialog, which is what the markers name.
TARGET_BY_CLASS: dict[str, TargetScreen] = {
    "FileInfoDialog": TargetScreen(
        name="file info dialog",
        markers=("fileinfodialog",),
        action="open a file's info dialog",
    ),
    "DeleteTask": TargetScreen(
        name="delete confirmation",
        # Amaze's Material dialog and the platform dialog both count; a
        # build that uses either has reached the delete flow.
        markers=("buttondefaultpositive",),
        action="delete a file",
    ),
    "RenameTask": TargetScreen(
        name="rename dialog",
        markers=("new_name",),
        action="rename a file",
    ),
    "CompressTask": TargetScreen(
        name="compress dialog",
        markers=("compress",),
        action="compress a file into an archive",
    ),
    "CardBrowser": TargetScreen(
        name="card browser",
        markers=("card_browser", "cardbrowser"),
        action="open the card browser",
    ),
    "DeckPicker": TargetScreen(
        name="deck list",
        markers=("deckpicker",),
        action="open the deck list",
    ),
    "NoteEditor": TargetScreen(
        name="note editor",
        markers=("noteeditor", "note_editor"),
        action="open the note editor",
    ),
    "FormChooserList": TargetScreen(
        name="form list",
        markers=("formchooserlist",),
        action="open the form list",
    ),
    "CustomStudyDialog": TargetScreen(
        name="custom study dialog",
        markers=("custom_study", "customstudy"),
        action="create a custom study session",
    ),
    "DebugInformation": TargetScreen(
        name="debug information",
        markers=("debug_information", "debuginformation"),
        action="open the debug information screen",
    ),
}


def target_for(frames: list[str]) -> TargetScreen | None:
    """The screen a crash's stack names, or None when it names none.

    A crash whose frames are all platform code has no app screen to reach;
    reporting one would invent a target.
    """
    for frame in frames:
        for fragment, target in TARGET_BY_CLASS.items():
            if fragment in frame:
                return TargetScreen(
                    name=target.name,
                    markers=target.markers,
                    action=target.action,
                    matched_class=fragment,
                )
    return None


def reached(ui_text: str, target: TargetScreen) -> ReachResult:
    """Whether a final UI dump shows the target screen.

    Every marker has to appear.  One marker would accept a dialog that merely
    mentions the word, and the whole point is to distinguish "the agent
    opened this dialog" from "the agent was somewhere in this app".
    """
    lowered = (ui_text or "").casefold()
    seen = [m for m in target.markers if m.casefold() in lowered]
    missing = [m for m in target.markers if m not in seen]
    return ReachResult(
        version="",
        target=target.name,
        reached=not missing,
        markers_seen=seen,
        missing=missing,
    )


def summarise(results: list[ReachResult]) -> dict:
    """Reach rate over a set of runs, with the targets it covered."""
    if not results:
        return {"runs": 0, "reached": 0, "rate": 0.0, "targets": {}}
    by_target: dict[str, list[bool]] = {}
    for result in results:
        by_target.setdefault(result.target, []).append(result.reached)
    return {
        "runs": len(results),
        "reached": sum(1 for r in results if r.reached),
        "rate": sum(1 for r in results if r.reached) / len(results),
        "targets": {
            name: {"runs": len(hits), "reached": sum(hits)}
            for name, hits in sorted(by_target.items())
        },
    }

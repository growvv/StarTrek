"""Turn a crash's stack into the task that reaches it.

The dataset records *where* a build crashes, not what a user did to get
there.  Handing an agent the dataset's `function_description` — a page
description such as "the current page is a navigation menu" — asks it to
look at a menu, which cannot delete anything and therefore cannot reach a
crash inside `DeleteTask`.

The stack names the code that died, and that code names the user action:
`DeleteTask.onPostExecute` is reached by deleting a file; `CardBrowser` with
a null `SearchView` is reached by opening the card browser.  This module maps
those class names onto user-level tasks and refuses when it cannot — a
guessed task would measure the guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Code that only runs for one user action, mapped to that action's task.
# Keyed by a fragment of the app frame's class name; the value is the task an
# agent can carry out.  Entries are added only when a crash in the dataset
# demonstrates them.
ACTION_BY_CLASS = {
    "DeleteTask": "delete a file",
    "CopyTask": "copy a file to another folder",
    "MoveTask": "move a file into another folder",
    "RenameTask": "rename a file",
    "CompressTask": "compress a file into an archive",
    "ExtractTask": "extract an archive",
    "CardBrowser": "open the card browser",
    "DeckPicker": "open a deck from the deck list",
    "Reviewer": "start reviewing a deck",
    "NoteEditor": "edit a note",
    "Gallery": "open a note's picture gallery",
    "Settings": "open the app's settings screen",
    "Search": "search the current list",
    # Added from the dataset's own stacks: each names code that only runs for
    # one user action, so the action is what reaches it.
    "HistoryRecyclerViewAdapter": "open a diary entry from the history list",
    "FavoritesWriter": "export favourites",
    "BookmarkControl": "save or update a bookmark label",
    "BookmarkDBAdapter": "save or update a bookmark label",
    "FileInfoDialog": "open a file's info dialog",
    "FormChooserList": "open the form list",
    "CustomStudyDialog": "create a custom study session",
    "DebugInformation": "open the debug information screen",
}

# Which attribute of the dataset's own graph entry describes the screen the
# task starts from.
_NOT_AN_ACTION = re.compile(
    r"^(the current page|this page|the page|a page)\b", re.IGNORECASE
)


@dataclass
class BugTask:
    """A task derived from a crash, and how confident the derivation is."""

    text: str
    source: str
    matched_class: str = ""

    @property
    def derived(self) -> bool:
        return bool(self.matched_class)


def app_frames(frames: list[str]) -> list[str]:
    """The stack frames that belong to the app, not to the platform."""
    return [
        frame
        for frame in frames
        if not frame.startswith(
            ("java.", "android.", "androidx.", "kotlin.", "dalvik.")
        )
    ]


def action_from_frames(frames: list[str]) -> str:
    """The user action the crashing code performs, or '' when unknown."""
    for frame in app_frames(frames):
        for fragment, action in ACTION_BY_CLASS.items():
            if fragment in frame:
                return action
    return ""


def task_for(version, goal: str = "") -> BugTask | None:
    """A task that can reach this build's crash.

    The stack wins over the dataset's page description: the stack names the
    code that died, and that code is reached by one user action.  When the
    stack names nothing known, a description that is itself an action is
    used; a page description is not, because acting on it cannot reach a
    crash in a task the page does not run.
    """
    for crash in version.crashes:
        action = action_from_frames(crash.frames)
        if action:
            return BugTask(
                text=_task_text(action),
                source="crash stack",
                matched_class=action,
            )
    if goal and not _NOT_AN_ACTION.match(goal.strip()):
        return BugTask(text=goal.strip(), source="dataset goal")
    return None


def _task_text(action: str) -> str:
    """Phrase the action as a goal an agent can be given."""
    return f"In the app, {action} and leave the result visible on screen."


def coverage(versions) -> dict:
    """How many versions have a derivable task, and which do not."""
    derivable: list[str] = []
    underivable: list[str] = []
    for version in versions:
        task = task_for(version)
        (derivable if task else underivable).append(version.id)
    return {
        "derivable": len(derivable),
        "underivable": len(underivable),
        "derivable_ids": derivable,
        "underivable_ids": underivable,
    }

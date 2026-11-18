"""A screen has an identity, and an agent that cannot tell screens apart gets lost.

Markor 0.3.9's run shows the failure: the agent tapped the file row, which
opened the editor, and then spent fourteen steps looking for the file-info
action in the editor's overflow menu.  Its plan was right; it never noticed
the screen had changed.

The identity here is what a person would say they are looking at: the
activity's title, the controls that only one screen has.  It is derived from
the same UI text the agent already receives, so it costs no extra call.
"""

from __future__ import annotations

import re

# Controls that identify a screen, most specific first.  A screen is named by
# the first one present; the order matters because a toolbar exists on many
# screens and a file editor's own widget on one.
SCREEN_MARKERS = (
    ("file editor", ("highlighting_editor", "document__fragment__edit")),
    ("note editor", ("detail_title", "detail_content")),
    ("file info dialog", ("file_info", "dialog_file")),
    ("share sheet", ("intentresolver", "chooser")),
    ("search", ("menu_search", "search_button", "search_src_text")),
    ("settings", ("preference", "settings")),
    ("file list", ("note_title", "firstline", "opoc_filesystem_item__title")),
    ("navigation drawer", ("nav_notebook", "nav_todo", "nav_more")),
)


def screen_identity(ui_text: str, activity: str = "") -> str:
    """What screen this UI text shows, in a form the agent can compare.

    The activity name is included because two screens of one app can share
    every control name — a list and a filtered list, a note and a note in a
    folder — while the activity differs.
    """
    lowered = (ui_text or "").lower()
    for label, markers in SCREEN_MARKERS:
        if any(marker in lowered for marker in markers):
            short = activity.rsplit(".", 1)[-1] if activity else ""
            return f"{label} ({short})" if short else label
    short = activity.rsplit(".", 1)[-1] if activity else ""
    return f"unknown ({short})" if short else "unknown"


def changed(before: str, after: str) -> bool:
    """Whether an action moved the agent to a different screen."""
    return before != after


def describe(identity: str, previous: str = "") -> str:
    """One line for the observation: where the agent is, and whether it moved."""
    if not previous:
        return f"Current screen: {identity}"
    if previous == identity:
        return (
            f"Current screen: {identity} — unchanged since the last action"
        )
    return f"Current screen: {identity} — changed from {previous}"

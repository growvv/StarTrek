"""Migrate a card written before cards became contracts.

The only change is the removal of the ``Steps`` section: a card used to
record the taps that had worked, and a contract names no UI action.  Every
other byte is preserved, which is what makes the migration idempotent and
keeps the diff of the 93 existing cards readable.
"""

from __future__ import annotations

import re

_STEPS_RE = re.compile(r"^\*\*Steps\s*:?\*\*\s*:?\s*$")
_HEADING_RE = re.compile(r"^\*\*[^*]+\*\*\s*:?")


def migrate(text: str) -> str:
    """Drop the Steps section, and nothing else.

    The section starts at a ``**Steps**`` heading and runs to the next
    ``**...**`` heading or the end of the file.  A card that has no Steps
    section comes back unchanged, so running the migration twice is safe.
    """
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if skipping:
            if _HEADING_RE.match(stripped) and not _STEPS_RE.match(stripped):
                skipping = False
                out.append(line)
            continue
        if _STEPS_RE.match(stripped):
            skipping = True
            continue
        out.append(line)
    return "".join(out)

"""What graph construction spent on semantic edge inference.

The construction journal records one frame per write, so the model calls are
visible as a sequence: a semantic-inference call writes its frame directly
after the write that preceded it, and the time between the two timestamps is
that call's duration.  Counting the frames counts the calls.

This is the measurement that made the quadratic build visible: a builder that
re-derives every edge after each mined trace records one call per trace, so
the same function of the whole card set runs once per growing prefix.
"""

from __future__ import annotations

from datetime import datetime

SEMANTIC = "semantic edges"


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def semantic_cost(frames: list[dict]) -> dict:
    """Calls and seconds spent inferring semantic edges in one journal."""
    calls = 0
    seconds = 0.0
    previous: datetime | None = None
    for frame in frames:
        reason = str(frame.get("reason") or "")
        stamp = frame.get("ts")
        if not isinstance(stamp, str) or not stamp:
            continue
        now = _time(stamp)
        if previous is not None and reason.startswith(SEMANTIC):
            calls += 1
            seconds += (now - previous).total_seconds()
        previous = now
    return {"calls": calls, "seconds": round(seconds, 1)}

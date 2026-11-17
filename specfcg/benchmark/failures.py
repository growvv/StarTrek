"""Failure taxonomy for benchmark runs.

Labels follow the stage-reporting requirement: a task that exceeds the step
budget, loops, crashes, or cannot be planned is a failure, and the reason is
recorded rather than folded into a generic "failed".
"""

from __future__ import annotations

FAILURE_TYPES = (
    "timeout",
    "init_failure",
    "app_crash",
    "no_plan",
    "step_limit",
    "loop_detected",
    "action_failure",
    "oracle_error",
    "goal_oracle_failure",
)


def classify_failure(
    *,
    success: bool,
    timed_out: bool,
    crashed: bool,
    init_error: str,
    no_plan: bool,
    steps: int,
    max_steps: int,
    looped: bool,
    action_failed: bool,
    oracle_error: str,
) -> str | None:
    if success:
        return None
    if timed_out:
        return "timeout"
    if init_error:
        return "init_failure"
    if crashed:
        return "app_crash"
    if no_plan:
        return "no_plan"
    if steps >= max_steps:
        return "step_limit"
    if looped:
        return "loop_detected"
    if action_failed:
        return "action_failure"
    if oracle_error:
        return "oracle_error"
    return "goal_oracle_failure"

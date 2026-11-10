"""Run a scripted action list on a device and record a SpecFCG trace."""

from __future__ import annotations

import time
from typing import Any

from specfcg.executor.device import Device
from specfcg.models import Step, Trace
from specfcg.traces.recorder import TraceRecorder


def _wait_seconds(spec: dict[str, Any]) -> float:
    try:
        return max(0.0, float(spec.get("wait", 1.0)))
    except (TypeError, ValueError):
        return 0.0


def run_actions(
    device: Device,
    actions: list[dict[str, Any]],
    *,
    app: str,
    trace_id: str,
    goal: str = "",
    metadata: dict[str, Any] | None = None,
    sleep=time.sleep,
) -> Trace:
    """Execute action specs, recording before/after UI state for each one."""
    initial_state = device.dump_ui()
    state = initial_state
    recorder = TraceRecorder(app, trace_id)

    for spec in actions:
        if not isinstance(spec, dict):
            continue
        action = str(spec.get("action", ""))
        target = str(spec.get("target", ""))
        args = str(spec.get("args", ""))
        before = state
        success = device.execute(action, target, args)
        sleep(_wait_seconds(spec))
        after = device.dump_ui()
        state = after
        recorder.record(
            Step(
                action=action,
                target=target,
                args=args,
                before_state=before,
                after_state=after,
                success=success,
            )
        )

    trace = recorder.trace()
    trace.start_state = initial_state
    trace.goal = goal
    if metadata:
        trace.metadata.update(metadata)
    return trace

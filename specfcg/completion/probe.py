"""Execute capability probe plans on a device and record a trace."""

from __future__ import annotations

import uuid

from specfcg.executor.device import Device
from specfcg.models import FunctionCard, MissingCapability, Step, Trace
from specfcg.planner.compiler import StepCompiler


class DeviceProbe:
    """Walks a hypothesized probe plan on the device and records the trace.

    A probe is a walk, not a script written in advance.  Its later steps act
    on screens that do not exist yet ("open the dialog", then "tap OK"
    inside it), so compiling the whole plan against the starting screen
    names controls that are not there.  Each step is compiled against the
    screen it will actually run on, and a miss ends the walk -- the steps
    that did run are evidence of real behavior, so they are kept.
    """

    def __init__(self, device: Device, compiler: StepCompiler) -> None:
        self.device = device
        self.compiler = compiler

    def run(
        self, capability: MissingCapability, state: str
    ) -> Trace | None:
        if not capability.probe:
            return None

        trace = Trace(
            trace_id=f"probe-{uuid.uuid4().hex}",
            app="",
            start_state=state,
            goal=capability.intent or capability.name,
        )
        current_state = state
        for line in capability.probe:
            card = FunctionCard(
                name=capability.name,
                intent=capability.intent or capability.name,
                inputs=list(capability.inputs),
                preconditions=capability.preconditions,
                postconditions=capability.postconditions,
                effects_outputs="",
                steps=[line],
            )
            actions = self.compiler.compile(card, {}, state=current_state)
            if not actions:
                break
            action = actions[0]
            before = current_state
            succeeded = self.device.execute(
                action.action, action.target, action.args
            )
            after = self.device.dump_ui()
            trace.steps.append(
                Step(
                    action=action.action,
                    target=action.target,
                    args=action.args,
                    before_state=before,
                    after_state=after,
                    success=succeeded,
                )
            )
            current_state = after
            if not succeeded:
                break
        if not trace.steps:
            return None
        trace.metadata["final_state"] = current_state
        return trace

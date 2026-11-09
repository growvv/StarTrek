"""Execute capability probe plans on a device and record a trace."""

from __future__ import annotations

import uuid

from specfcg.executor.device import Device
from specfcg.models import FunctionCard, MissingCapability, Step, Trace
from specfcg.planner.compiler import StepCompiler


class DeviceProbe:
    """Compiles a hypothesized probe plan into actions and executes it."""

    def __init__(self, device: Device, compiler: StepCompiler) -> None:
        self.device = device
        self.compiler = compiler

    def run(
        self, capability: MissingCapability, state: str
    ) -> Trace | None:
        if not capability.probe:
            return None

        card = FunctionCard(
            name=capability.name,
            intent=capability.intent or capability.name,
            inputs=list(capability.inputs),
            preconditions=capability.preconditions,
            postconditions=capability.postconditions,
            effects_outputs="",
            steps=list(capability.probe),
        )
        actions = self.compiler.compile(card, {})
        trace = Trace(
            trace_id=f"probe-{uuid.uuid4().hex}",
            app="",
            start_state=state,
            goal=capability.intent or capability.name,
        )
        current_state = state
        for action in actions:
            before = self.device.dump_ui()
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
                return None
        trace.metadata["final_state"] = current_state
        return trace

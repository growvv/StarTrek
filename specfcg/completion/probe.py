"""Probe a hypothesized capability by handing it to the GUI agent."""

from __future__ import annotations

import uuid

from specfcg.executor.agent import GuiAgent
from specfcg.models import MissingCapability, Trace


def render_probe_task(capability: MissingCapability, state: str) -> str:
    """Render the hypothesis as a task description.

    The capability is a claim about what the app can do: an intent, what must
    hold first, what must hold after.  The probe asks the agent to establish
    that claim from the current screen.  It says nothing about how -- naming
    controls before anyone has seen the screen was the mistake the old
    compiled probe made.
    """
    lines = [
        f"Overall goal: {capability.intent or capability.name}",
        "",
        f"Preconditions: {capability.preconditions or 'none stated'}",
        f"Postconditions: {capability.postconditions or 'none stated'}",
    ]
    if state:
        lines.extend(["", "Current state:", state[:2000]])
    return "\n".join(lines)


class AgentProbe:
    """Walk a capability hypothesis with the agent and record the trace."""

    def __init__(self, agent: GuiAgent, max_steps: int = 10) -> None:
        self.agent = agent
        self.max_steps = max_steps

    def run(
        self, capability: MissingCapability, state: str, app: str = ""
    ) -> Trace | None:
        task = render_probe_task(capability, state)
        result = self.agent.run(task, self.max_steps, app=app)
        if not result.steps:
            return None
        return Trace(
            trace_id=f"probe-{uuid.uuid4().hex}",
            app=app,
            start_state=state,
            goal=capability.intent or capability.name,
            steps=list(result.steps),
            metadata={
                "final_state": result.final_ui,
                "probe_task": task,
            },
        )

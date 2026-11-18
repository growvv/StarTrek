"""The GUI agent protocol and its execution trace."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from specfcg.models import Step


@dataclass
class AgentTrace:
    """What one agent run did, and where it started and ended.

    ``done`` is the agent's own claim.  It is recorded because it is useful
    when reading a failed run, and it is never the verdict: the programmatic
    goal check decides success.
    """

    steps: list[Step] = field(default_factory=list)
    initial_ui: str = ""
    final_ui: str = ""
    done: bool = False
    error: str = ""


@runtime_checkable
class GuiAgent(Protocol):
    """A GUI agent, with two methods and no policy.

    ``observe`` returns the compact UI text the planner reads, and ``run``
    carries out a task description.  The app travels with each call because
    one pipeline serves every app.  How the agent decides what to tap is its
    own business; nothing here names an action.
    """

    def observe(self, app: str) -> str: ...

    def run(self, task: str, max_steps: int, *, app: str) -> AgentTrace: ...


class ScriptedAgent:
    """A GuiAgent with canned results, recording what it was asked to do.

    The offline pipeline uses it so an end-to-end run needs no phone, and the
    tests use it to assert what the executor asked for.
    """

    def __init__(
        self,
        steps: list[Step] | None = None,
        done: bool = False,
        initial_ui: str = "notes list",
        final_ui: str = "notes list",
        error: str = "",
    ) -> None:
        self.steps = list(steps or [])
        self.done = done
        self.initial_ui = initial_ui
        self.final_ui = final_ui
        self.error = error
        self.tasks: list[str] = []
        self.apps: list[str] = []
        self.max_steps: list[int] = []

    def observe(self, app: str) -> str:
        return self.initial_ui

    def run(self, task: str, max_steps: int, *, app: str) -> AgentTrace:
        self.tasks.append(task)
        self.apps.append(app)
        self.max_steps.append(max_steps)
        return AgentTrace(
            steps=list(self.steps),
            initial_ui=self.initial_ui,
            final_ui=self.final_ui,
            done=self.done,
            error=self.error,
        )

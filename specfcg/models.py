"""Shared data models for SpecFCG."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EdgeType = Literal["enables", "dataflow", "sequence", "calls"]
FailureType = Literal[
    "precondition_mismatch",
    "widget_failure",
    "trace_failure",
    "postcondition_failure",
    "goal_failure",
    "environment_failure",
    "check_error",
]

EDGE_PRIORITY: tuple[str, ...] = ("enables", "dataflow", "sequence", "calls")


def as_bool(value: Any) -> bool:
    """Interpret bool-like model output without trusting string truthiness."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "y"}
    return bool(value)


@dataclass
class Step:
    action: str
    target: str = ""
    args: str = ""
    before_state: str = ""
    after_state: str = ""
    success: bool = True


@dataclass
class Trace:
    trace_id: str
    app: str
    steps: list[Step] = field(default_factory=list)
    start_state: str = ""
    goal: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FunctionCard:
    name: str
    intent: str
    inputs: list[str]
    preconditions: str
    postconditions: str
    effects_outputs: str
    steps: list[str]
    evidence: list[str] = field(default_factory=list)
    success_count: int = 0
    attempt_count: int = 0


@dataclass
class Edge:
    from_card: str
    to_card: str
    type: EdgeType
    description: str = ""
    evidence: list[str] = field(default_factory=list)


@dataclass
class Graph:
    cards: dict[str, FunctionCard] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    def outgoing(self, name: str) -> list[Edge]:
        return [edge for edge in self.edges if edge.from_card == name]

    def incoming(self, name: str) -> list[Edge]:
        return [edge for edge in self.edges if edge.to_card == name]

    def entry_cards(self) -> list[str]:
        """Cards with no incoming edge, in insertion order."""
        targets = {edge.to_card for edge in self.edges}
        return [name for name in self.cards if name not in targets]


@dataclass
class Goal:
    description: str
    app: str = ""
    id: str = ""
    assertions: list[str] = field(default_factory=list)


@dataclass
class PlanStep:
    card: str
    action: str
    target: str = ""
    args: str = ""
    instance: int = 0


@dataclass
class TestPlan:
    goal: Goal
    path: list[str] = field(default_factory=list)
    steps: list[PlanStep] = field(default_factory=list)
    assertions: list[str] = field(default_factory=list)
    app: str = ""


@dataclass
class RunResult:
    plan: TestPlan | None = None
    success: bool = False
    goal_success: bool = False
    failure_type: FailureType | None = None
    new_trace: Trace | None = None
    step_results: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""


@dataclass
class CardPatch:
    new_cards: list[FunctionCard] = field(default_factory=list)
    updates: list[dict[str, Any]] = field(default_factory=list)
    segments: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class GraphPatch:
    new_cards: list[FunctionCard] = field(default_factory=list)
    card_updates: list[dict[str, Any]] = field(default_factory=list)
    edge_updates: list[dict[str, Any]] = field(default_factory=list)
    split: list[dict[str, Any]] = field(default_factory=list)
    merge: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""


@dataclass
class MissingCapability:
    name: str
    intent: str = ""
    preconditions: str = ""
    postconditions: str = ""
    inputs: list[str] = field(default_factory=list)
    probe: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence: str = ""

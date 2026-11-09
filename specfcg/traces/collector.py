"""Trace collector protocol and fixture-backed collector."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from specfcg.models import Trace
from specfcg.traces.recorder import TraceStore


class TraceCollector(Protocol):
    def collect(
        self, app: str, policy: str = "greedy_dfs"
    ) -> list[Trace]: ...


class FixtureCollector:
    """Read pre-recorded traces from `<root>/traces/`."""

    def __init__(self, root: Path) -> None:
        self.store = TraceStore(root)

    def collect(
        self, app: str, policy: str = "greedy_dfs"
    ) -> list[Trace]:
        return [trace for trace in self.store.all() if trace.app == app]

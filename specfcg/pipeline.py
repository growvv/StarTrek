"""Wire the SpecFCG components into an end-to-end pipeline."""

from __future__ import annotations

import logging
from typing import Any

from specfcg.cards.store import CardStore
from specfcg.completion.completer import CapabilityCompleter
from specfcg.config import AppConfig
from specfcg.executor.device import Device
from specfcg.executor.executor import Executor
from specfcg.graph.store import GraphStore
from specfcg.llm.client import LLMClient
from specfcg.maintainer.builder import EdgeBuilder
from specfcg.maintainer.miner import CardMiner
from specfcg.maintainer.updater import GraphUpdater
from specfcg.models import (
    CardPatch,
    Edge,
    Goal,
    Graph,
    GraphPatch,
    RunResult,
    TestPlan,
    Trace,
)
from specfcg.planner.planner import Planner

logger = logging.getLogger(__name__)


def _edge_update(edge: Edge) -> dict[str, Any]:
    return {
        "from": edge.from_card,
        "to": edge.to_card,
        "type": edge.type,
        "action": "add",
        "description": edge.description,
        "evidence": list(edge.evidence),
    }


class Pipeline:
    def __init__(
        self,
        config: AppConfig,
        llm: LLMClient,
        device: Device,
        store: GraphStore,
        card_store: CardStore,
        miner: CardMiner,
        builder: EdgeBuilder,
        planner: Planner,
        executor: Executor,
        updater: GraphUpdater,
        completer: CapabilityCompleter,
    ) -> None:
        self.config = config
        self.llm = llm
        self.device = device
        self.store = store
        self.card_store = card_store
        self.miner = miner
        self.builder = builder
        self.planner = planner
        self.executor = executor
        self.updater = updater
        self.completer = completer
        self.graph: Graph = planner.graph

    def _reload_graph(self) -> Graph:
        self.graph = self.store.load()
        self.planner.graph = self.graph
        self.executor.graph = self.graph
        return self.graph

    def _apply_patch(
        self, patch: GraphPatch, *, backup: bool = False
    ) -> None:
        version = None
        if backup:
            version = self.store.backup()
        try:
            self.store.apply_patch(patch)
        except Exception:
            if version is not None:
                self.store.restore(version)
            raise
        self._reload_graph()

    def mine_trace(self, trace: Trace) -> CardPatch:
        patch = self.miner.mine(trace)
        cards = self.card_store.all()
        for card in patch.new_cards:
            cards[card.name] = card
        edges = self.builder.sequence_edges(cards, patch.segments)
        self._apply_patch(
            GraphPatch(
                new_cards=patch.new_cards,
                card_updates=patch.updates,
                edge_updates=[_edge_update(edge) for edge in edges],
                reason=f"mined trace {trace.trace_id}",
            )
        )
        return patch

    def build_graph(self, segments: list[dict[str, Any]]) -> list[Edge]:
        edges = self.builder.build(self.card_store.all(), segments)
        self._apply_patch(
            GraphPatch(
                edge_updates=[_edge_update(edge) for edge in edges],
                reason="rebuilt graph",
            )
        )
        return edges

    def plan(
        self, goal_text: str, state: str = "", app: str = ""
    ) -> TestPlan | None:
        return self.planner.plan(
            Goal(description=goal_text, app=app), state
        )

    def execute_goal(
        self, goal_text: str, state: str = "", app: str = ""
    ) -> RunResult | None:
        plan = self.plan(goal_text, state, app)
        if plan is None:
            return None
        return self.executor.execute(plan)

    def refine(
        self, goal_text: str, state: str = "", app: str = ""
    ) -> GraphPatch | None:
        plan = self.plan(goal_text, state, app)
        if plan is None:
            return None
        result = self.executor.execute(plan)
        patch = self.updater.update(result)
        self._apply_patch(patch, backup=not result.success)
        return patch

    def complete(
        self, goal_text: str, state: str = "", app: str = ""
    ) -> GraphPatch | None:
        patch = self.completer.complete(
            Goal(description=goal_text, app=app), state
        )
        if patch is not None:
            self._apply_patch(patch, backup=True)
        return patch

    def run_goal(
        self,
        goal_text: str,
        state: str = "",
        max_rounds: int = 2,
        app: str = "",
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "goal": goal_text,
            "success": False,
            "goal_success": False,
            "rounds": 0,
            "path": [],
            "failure_type": None,
            "error": "",
            "patch_reason": "",
            "completion_reason": "",
        }
        for round_index in range(max(1, max_rounds)):
            summary["rounds"] = round_index + 1
            plan = self.plan(goal_text, state, app)
            if plan is None:
                completion = self.complete(goal_text, state, app)
                if completion is None:
                    summary["error"] = (
                        "no plan and no capability completion"
                    )
                else:
                    summary["completion_reason"] = completion.reason
                continue

            result = self.executor.execute(plan)
            patch = self.updater.update(result)
            self._apply_patch(patch, backup=not result.success)
            summary.update(
                {
                    "success": result.success,
                    "goal_success": result.goal_success,
                    "path": list(plan.path),
                    "failure_type": result.failure_type,
                    "error": result.error,
                    "patch_reason": patch.reason,
                }
            )
            if result.success:
                return summary
            if result.new_trace is not None and result.new_trace.steps:
                state = (
                    result.new_trace.steps[-1].after_state or state
                )
        return summary

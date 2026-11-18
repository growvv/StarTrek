"""Wire the SpecFCG components into an end-to-end pipeline."""

from __future__ import annotations

import json
import logging
from pathlib import Path
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
from specfcg.traces.recorder import trace_digest

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
        self,
        patch: GraphPatch,
        *,
        backup: bool = False,
        origin: dict[str, Any] | None = None,
    ) -> None:
        version = None
        if backup:
            version = self.store.backup()
        try:
            self.store.apply_patch(patch, origin=origin)
        except Exception:
            if version is not None:
                self.store.restore(version)
            raise
        self._reload_graph()

    def mine_trace(self, trace: Trace) -> CardPatch:
        digest = trace_digest(trace)
        if self.store.applied(digest):
            logger.info(
                "trace %s is already in the graph; nothing to mine",
                trace.trace_id,
            )
            return CardPatch()
        patch = self.miner.mine(trace)
        cards = self.card_store.all()
        for card in patch.new_cards:
            cards[card.name] = card
        edges = self.builder.sequence_edges(cards, patch.segments)
        names = ", ".join(card.name for card in patch.new_cards) or "no new card"
        self._apply_patch(
            GraphPatch(
                new_cards=patch.new_cards,
                card_updates=patch.updates,
                edge_updates=[_edge_update(edge) for edge in edges],
                reason=f"mined trace {trace.trace_id} -> {names}",
            ),
            origin={
                "kind": "trace",
                "id": trace.trace_id,
                "digest": digest,
            },
        )
        return patch

    def build_graph(self, segments: list[dict[str, Any]]) -> list[Edge]:
        cards = self.card_store.all()
        result = self.builder.build(cards, segments)
        self._write_same_function(result.same_function)
        self._apply_patch(
            GraphPatch(
                edge_updates=[_edge_update(edge) for edge in result.edges],
                reason=f"semantic edges over {len(cards)} card"
                f"{'s' if len(cards) != 1 else ''}",
            )
        )
        return result.edges

    def _write_same_function(self, groups: list[list[str]]) -> None:
        """Record the model's same-function groups beside the edges.

        This is a diagnosis, not a score: the groups are read by whoever
        wants them and never consumed by the planner.  Writing them on every
        build keeps them in step with the cards they describe.
        """
        path = Path(self.store.root) / "graph" / "same_function.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"groups": groups}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def observe(self, app: str) -> str:
        """The screen the agent sees, for planning a plan it will execute.

        Planning from the same client the agent acts through is what keeps
        the state a plan is made from equal to the state it acts on.
        """
        return self.executor.agent.observe(app)

    def plan(
        self, goal_text: str, state: str = "", app: str = ""
    ) -> TestPlan | None:
        return self.planner.plan(
            Goal(description=goal_text, app=app), state
        )

    def plan_path(
        self, goal_text: str, path: list[str], state: str = "", app: str = ""
    ) -> TestPlan | None:
        """Compile one specific card path, without searching for another.

        A probe predicts the path it expects the graph to take; executing
        that path is what makes the prediction testable.  Searching again
        would measure a different path than the one whose confidence was
        reported.
        """
        goal = Goal(description=goal_text, app=app)
        return self.planner.compile_path(
            goal, list(path), [goal_text] * len(path), state
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

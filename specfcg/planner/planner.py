"""Goal-driven planning over the Function Contract Graph."""

from __future__ import annotations

import logging

from specfcg.graph.search import search
from specfcg.llm.client import LLMClient, LLMParseError
from specfcg.models import Goal, Graph, TestPlan
from specfcg.planner.binding import ParamBinder
from specfcg.planner.compiler import StepCompiler
from specfcg.planner.retrieval import CardRetriever

logger = logging.getLogger(__name__)

_CAN_SCHEMA = '{"can_execute": true, "reason": "why"}'
_GOAL_SCHEMA = '{"is_goal": true, "reason": "why"}'


class Planner:
    def __init__(
        self,
        graph: Graph,
        llm: LLMClient,
        retriever: CardRetriever,
        binder: ParamBinder,
        compiler: StepCompiler,
        strategy: str = "astar",
        max_depth: int = 8,
    ) -> None:
        self.graph = graph
        self.llm = llm
        self.retriever = retriever
        self.binder = binder
        self.compiler = compiler
        self.strategy = strategy
        self.max_depth = max_depth
        self._can_cache: dict[tuple[str, str], bool] = {}
        self._goal_cache: dict[tuple[str, str, str], bool] = {}

    def _can_execute(self, card: str, state: str) -> bool:
        key = (card, state)
        if key not in self._can_cache:
            card_obj = self.graph.cards.get(card)
            if card_obj is None:
                return False
            prompt = (
                f"Current state:\n{state[:4000]}\n\n"
                f"Card: {card_obj.name}\nIntent: {card_obj.intent}\n"
                f"Preconditions: {card_obj.preconditions}\n\n"
                "Can this card execute in this state?"
            )
            try:
                data = self.llm.complete_json(prompt, _CAN_SCHEMA)
            except LLMParseError as exc:
                logger.warning("can_execute check failed: %s", exc)
                result = False
            else:
                result = (
                    bool(data.get("can_execute", False))
                    if isinstance(data, dict)
                    else False
                )
            self._can_cache[key] = result
        return self._can_cache[key]

    def _is_goal(self, card: str, goal: Goal, state: str) -> bool:
        key = (card, state, goal.description)
        if key not in self._goal_cache:
            card_obj = self.graph.cards.get(card)
            if card_obj is None:
                return False
            prompt = (
                f"Goal: {goal.description}\nCurrent state:\n{state[:4000]}\n\n"
                f"Card: {card_obj.name}\nIntent: {card_obj.intent}\n"
                f"Postconditions: {card_obj.postconditions}\n\n"
                "Does executing this card satisfy the goal or its "
                "postconditions?"
            )
            try:
                data = self.llm.complete_json(prompt, _GOAL_SCHEMA)
            except LLMParseError as exc:
                logger.warning("is_goal check failed: %s", exc)
                result = False
            else:
                result = (
                    bool(data.get("is_goal", False))
                    if isinstance(data, dict)
                    else False
                )
            self._goal_cache[key] = result
        return self._goal_cache[key]

    def plan(self, goal: Goal, state: str) -> TestPlan | None:
        candidates = self.retriever.retrieve(goal, self.graph.cards)
        if not candidates:
            return None
        allowed = set(candidates)

        def can_execute(card: str) -> bool:
            if card not in allowed:
                return False
            return self._can_execute(card, state)

        def is_goal(card: str) -> bool:
            return self._is_goal(card, goal, state)

        path = search(
            self.graph,
            None,
            can_execute,
            is_goal,
            self.strategy,  # type: ignore[arg-type]
            self.max_depth,
        )
        if path is None:
            return None

        prior_outputs: dict[str, str] = {}
        steps = []
        assertions = [goal.description]
        for name in path:
            card_obj = self.graph.cards.get(name)
            if card_obj is None:
                return None
            bindings = self.binder.bind(
                card_obj, goal, state, prior_outputs
            )
            if bindings is None:
                return None
            steps.extend(self.compiler.compile(card_obj, bindings))

            output_value = (
                next(iter(bindings.values()))
                if bindings
                else card_obj.effects_outputs
            )
            prior_outputs[f"{card_obj.name}.output"] = str(output_value)
            for param, value in bindings.items():
                prior_outputs[f"{card_obj.name}.{param}"] = str(value)
            if card_obj.postconditions:
                assertions.append(card_obj.postconditions)

        return TestPlan(
            goal=goal,
            path=path,
            steps=steps,
            assertions=assertions,
            app=goal.app,
        )

"""Goal-driven planning over the Function Contract Graph."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from specfcg.graph.search import search
from specfcg.llm.client import LLMClient, LLMParseError
from specfcg.models import Goal, Graph, TestPlan, as_bool
from specfcg.planner.binding import ParamBinder
from specfcg.planner.compiler import StepCompiler
from specfcg.planner.retrieval import CardRetriever

logger = logging.getLogger(__name__)

_CAN_SCHEMA = '{"can_execute": true}'
_GOAL_SCHEMA = '{"is_goal": true}'
_BATCH_SCHEMA = (
    '{"cards": [{"name": "create_note", "can_execute": true, '
    '"is_goal": false}], '
    '"plan": [{"card": "create_note", "subgoal": "create the note"}]}'
)
_PLAN_GOAL_SCHEMA = '{"is_goal": true}'


@dataclass
class _Proposal:
    card: str
    subgoal: str


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
        self._plan_goal_cache: dict[
            tuple[tuple[str, ...], str, str], bool
        ] = {}

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
                    as_bool(data.get("can_execute", False))
                    if isinstance(data, dict)
                    else False
                )
            self._can_cache[key] = result
        return self._can_cache[key]

    def _is_goal(
        self,
        card: str,
        goal: Goal,
        state: str,
        path: tuple[str, ...],
    ) -> bool:
        if len(path) > 1:
            return self._plan_completes_goal(path, goal, state)
        key = (card, state, goal.description)
        if key not in self._goal_cache:
            card_obj = self.graph.cards.get(card)
            if card_obj is None:
                return False
            prompt = (
                f"Goal: {goal.description}\nCurrent state:\n{state[:4000]}\n\n"
                f"Card: {card_obj.name}\nIntent: {card_obj.intent}\n"
                f"Postconditions: {card_obj.postconditions}\n\n"
                "Does executing this card, on its own, fully satisfy the "
                "entire goal (every part of it), rather than only one part?"
            )
            try:
                data = self.llm.complete_json(prompt, _GOAL_SCHEMA)
            except LLMParseError as exc:
                logger.warning("is_goal check failed: %s", exc)
                result = False
            else:
                result = (
                    as_bool(data.get("is_goal", False))
                    if isinstance(data, dict)
                    else False
                )
            self._goal_cache[key] = result
        return self._goal_cache[key]

    def _plan_completes_goal(
        self, path: tuple[str, ...], goal: Goal, state: str
    ) -> bool:
        """Ask whether the whole planned card sequence reaches the goal.

        A multi-card plan can satisfy a goal no single card satisfies, so
        the terminal-card check alone would reject valid compositions (and
        accept partial ones).
        """
        key = (path, goal.description, state)
        if key in self._plan_goal_cache:
            return self._plan_goal_cache[key]
        lines = []
        for index, name in enumerate(path, 1):
            card = self.graph.cards.get(name)
            if card is None:
                self._plan_goal_cache[key] = False
                return False
            lines.append(
                f"{index}. {name}: intent={card.intent!r}; "
                f"postconditions={card.postconditions!r}"
            )
        prompt = (
            f"Goal: {goal.description}\n"
            f"Plan (execution order): {' -> '.join(path)}\n"
            f"Current state before the plan:\n{state[:2000]}\n\n"
            f"Planned cards:\n" + "\n".join(lines) + "\n\n"
            "The cards execute in this order. Does the whole plan, once "
            "executed, fully satisfy the entire goal (every part of it)?"
        )
        try:
            data = self.llm.complete_json(prompt, _PLAN_GOAL_SCHEMA)
        except LLMParseError as exc:
            logger.warning("plan goal check failed: %s", exc)
            result = False
        else:
            result = (
                as_bool(data.get("is_goal", False))
                if isinstance(data, dict)
                else False
            )
        self._plan_goal_cache[key] = result
        return result

    def _prefetch(
        self, candidates: list[str], goal: Goal, state: str
    ) -> tuple[set[str], list[_Proposal]]:
        """Classify all candidate cards in a single LLM round trip.

        One call per card costs minutes on slow reasoning models. This
        answers both predicates for every candidate at once; whatever the
        response omits or mangles falls back to the per-card calls.
        """
        lines = "\n".join(
            f"- {name}: intent={self.graph.cards[name].intent!r}; "
            f"preconditions={self.graph.cards[name].preconditions!r}; "
            f"postconditions={self.graph.cards[name].postconditions!r}"
            for name in candidates
            if name in self.graph.cards
        )
        if not lines:
            return set(), []
        prompt = (
            f"Goal: {goal.description}\nCurrent state:\n{state[:4000]}\n\n"
            f"Cards:\n{lines}\n\n"
            "For each card decide:\n"
            "- can_execute: can the card run in this state?\n"
            "- is_goal: does executing this card, on its own, fully "
            "satisfy the goal?\n\n"
            "Also propose an ordered execution plan that fully achieves "
            "the goal from the current state, using only these cards. "
            'Each plan item is {"card": "<name>", "subgoal": "<what that '
            'step must accomplish>"}. You may use a card more than once '
            "when the goal needs several instances; give each occurrence "
            "a different subgoal. Use an empty plan if these cards "
            "cannot achieve the goal.\n"
            f"Return JSON {_BATCH_SCHEMA}."
        )
        try:
            data = self.llm.complete_json(prompt, _BATCH_SCHEMA)
        except LLMParseError as exc:
            logger.warning("batch predicate check failed: %s", exc)
            return set(), []
        raw_cards = data.get("cards") if isinstance(data, dict) else None
        if not isinstance(raw_cards, list):
            return set(), []
        classified: set[str] = set()
        for item in raw_cards:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or name not in self.graph.cards:
                continue
            self._can_cache[(name, state)] = as_bool(
                item.get("can_execute", False)
            )
            self._goal_cache[(name, state, goal.description)] = as_bool(
                item.get("is_goal", False)
            )
            classified.add(name)

        proposals: list[_Proposal] = []
        raw_plan = data.get("plan") if isinstance(data, dict) else None
        if isinstance(raw_plan, list):
            for item in raw_plan:
                if isinstance(item, dict):
                    card = item.get("card")
                    subgoal = item.get("subgoal")
                    if (
                        isinstance(card, str)
                        and isinstance(subgoal, str)
                        and card in self.graph.cards
                        and subgoal.strip()
                    ):
                        proposals.append(
                            _Proposal(card, subgoal.strip())
                        )
                elif isinstance(item, str) and item in self.graph.cards:
                    proposals.append(_Proposal(item, goal.description))
        return classified, proposals

    def _valid_proposal(
        self,
        proposals: list[_Proposal],
        allowed: set[str],
        state: str,
    ) -> bool:
        cards = [proposal.card for proposal in proposals]
        if not cards:
            return False
        if any(card not in allowed for card in cards):
            return False
        if not self._can_execute(cards[0], state):
            return False
        for previous, current in zip(cards, cards[1:]):
            if previous == current:
                continue
            if not any(
                edge.from_card == previous
                and edge.to_card == current
                and edge.type in {"enables", "sequence"}
                for edge in self.graph.edges
            ):
                return False
        return True

    def plan(self, goal: Goal, state: str) -> TestPlan | None:
        candidates = self.retriever.retrieve(goal, self.graph.cards)
        if not candidates:
            return None
        classified, proposals = self._prefetch(candidates, goal, state)
        allowed = set(candidates)

        def can_execute(card: str) -> bool:
            if card not in allowed:
                return False
            return self._can_execute(card, state)

        def is_goal(card: str, path: list[str]) -> bool:
            return self._is_goal(card, goal, state, tuple(path))

        if classified:
            starts = [
                name
                for name in candidates
                if name in classified
                and self._can_cache.get((name, state), False)
            ]
        else:
            starts = [
                name
                for name in self.graph.entry_cards()
                if name in allowed
            ]

        path: list[str] | None = None
        subgoals: list[str] = []
        if classified and self._valid_proposal(
            proposals, allowed, state
        ):
            proposed_path = [
                proposal.card for proposal in proposals
            ]
            if self._plan_completes_goal(
                tuple(proposed_path), goal, state
            ):
                path = proposed_path
                subgoals = [
                    proposal.subgoal for proposal in proposals
                ]

        if path is None:
            path = search(
                self.graph,
                None,
                can_execute,
                is_goal,
                self.strategy,  # type: ignore[arg-type]
                self.max_depth,
                starts=starts,
            )
            if path is None:
                return None
            subgoals = [goal.description] * len(path)

        prior_outputs: dict[str, str] = {}
        steps = []
        assertions = [goal.description]
        for instance, (name, subgoal) in enumerate(
            zip(path, subgoals)
        ):
            card_obj = self.graph.cards.get(name)
            if card_obj is None:
                return None
            step_goal = Goal(description=subgoal, app=goal.app)
            bindings = self.binder.bind(
                card_obj, step_goal, state, prior_outputs
            )
            if bindings is None:
                return None
            compiled = self.compiler.compile(card_obj, bindings)
            for step in compiled:
                step.instance = instance
            steps.extend(compiled)
            if subgoal and subgoal != goal.description:
                assertions.append(subgoal)

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

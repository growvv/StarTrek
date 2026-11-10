"""Turn execution results into validated GraphPatch proposals."""

from __future__ import annotations

import logging
import re
from typing import Any

from specfcg.graph.store import GraphStore
from specfcg.llm.client import LLMClient, LLMParseError
from specfcg.maintainer.builder import EdgeBuilder
from specfcg.models import (
    EDGE_PRIORITY,
    FailureType,
    FunctionCard,
    GraphPatch,
    RunResult,
)

logger = logging.getLogger(__name__)

_FAILURE_TYPES = {
    "precondition_mismatch",
    "widget_failure",
    "trace_failure",
    "postcondition_failure",
    "goal_failure",
    "environment_failure",
    "check_error",
}

_PATCH_SCHEMA = (
    '{"card_updates": [{"name": "create_note", "fields": {"Steps": ["..."]}}], '
    '"new_cards": [], "edge_updates": [{"from": "a", "to": "b", '
    '"type": "enables", "action": "add", "description": "..."}], '
    '"split": [], "merge": [], "reason": "..."}'
)

_EXECUTABLE_FIELDS = {
    "steps",
    "preconditions",
    "postconditions",
    "inputs",
    "effects_outputs",
}


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    text = str(value).strip()
    if not text or text.lower() in {"none", "n/a"}:
        return []
    return [
        part.strip()
        for part in re.split(r"[,\n]", text)
        if part.strip()
    ]


class GraphUpdater:
    def __init__(
        self,
        llm: LLMClient,
        store: GraphStore,
        builder: EdgeBuilder,
    ) -> None:
        self.llm = llm
        self.store = store
        self.builder = builder

    def classify_failure(
        self, result: RunResult
    ) -> FailureType | None:
        if result.success:
            return None
        if result.failure_type:
            return result.failure_type
        prompt = (
            f"Goal: {result.plan.goal.description if result.plan else 'unknown'}\n"
            f"Error: {result.error}\n"
            f"Executed steps: {len(result.step_results)}\n\n"
            "Classify the failure. Choose one: "
            + ", ".join(sorted(_FAILURE_TYPES))
        )
        try:
            data = self.llm.complete_json(
                prompt, '{"failure_type": "widget_failure", "reason": "..."}'
            )
        except LLMParseError:
            return "trace_failure"
        value = data.get("failure_type") if isinstance(data, dict) else None
        return value if value in _FAILURE_TYPES else "trace_failure"

    @staticmethod
    def _segments(result: RunResult) -> list[dict[str, Any]]:
        if result.new_trace is None:
            return []
        trace_id = result.new_trace.trace_id
        segments: list[dict[str, Any]] = []
        for index, item in enumerate(result.step_results):
            if not isinstance(item, dict):
                continue
            card = item.get("card")
            if card:
                segments.append(
                    {
                        "trace_id": trace_id,
                        "start": index,
                        "end": index,
                        "card": card,
                    }
                )
        if not segments and result.plan is not None:
            segments = [
                {
                    "trace_id": trace_id,
                    "start": index,
                    "end": index,
                    "card": name,
                }
                for index, name in enumerate(result.plan.path)
            ]
        return segments

    def _success_patch(self, result: RunResult) -> GraphPatch:
        cards = self.store.cards.all()
        counts: dict[str, int] = {}
        if result.plan is not None:
            for name in result.plan.path:
                counts[name] = counts.get(name, 0) + 1

        trace_id = (
            result.new_trace.trace_id if result.new_trace is not None else None
        )
        card_updates: list[dict[str, Any]] = []
        for name, count in counts.items():
            card = cards.get(name)
            if card is None:
                continue
            evidence = list(card.evidence)
            if trace_id and trace_id not in evidence:
                evidence.append(trace_id)
            card_updates.append(
                {
                    "name": name,
                    "fields": {
                        "evidence": evidence,
                        "success_count": card.success_count + count,
                        "attempt_count": card.attempt_count + count,
                    },
                }
            )

        edge_updates: list[dict[str, Any]] = []
        segments = self._segments(result)
        if segments:
            for edge in self.builder.sequence_edges(cards, segments):
                edge_updates.append(
                    {
                        "from": edge.from_card,
                        "to": edge.to_card,
                        "type": edge.type,
                        "action": "add",
                        "description": edge.description,
                        "evidence": edge.evidence,
                    }
                )
        return GraphPatch(
            card_updates=card_updates,
            edge_updates=edge_updates,
            reason="successful execution",
        )

    @staticmethod
    def _card_detail(card: FunctionCard) -> str:
        steps = (
            "\n".join(
                f"  {index}. {step}"
                for index, step in enumerate(card.steps, 1)
            )
            or "  (none)"
        )
        return (
            f"# {card.name}\n"
            f"Intent: {card.intent}\n"
            f"Inputs: {', '.join(card.inputs) or 'none'}\n"
            f"Preconditions: {card.preconditions}\n"
            f"Postconditions: {card.postconditions}\n"
            f"Steps:\n{steps}"
        )

    @staticmethod
    def _action_detail(result: RunResult) -> str:
        lines = []
        for item in result.step_results:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- card={item.get('card')} "
                f"action={item.get('action')} "
                f"target={item.get('target')!r} "
                f"args={item.get('args')!r} "
                f"success={item.get('success')}"
            )
        return "\n".join(lines) or "- (none recorded)"

    def _failure_patch(self, result: RunResult) -> GraphPatch:
        cards = self.store.cards.all()
        edges = self.store.edges()
        edge_lines = [
            f"{edge.from_card} -> {edge.to_card} [{edge.type}]"
            for edge in edges
        ]
        path_names = result.plan.path if result.plan is not None else []
        path_cards = [
            self._card_detail(cards[name])
            for name in path_names
            if name in cards
        ]
        if not path_cards:
            path_cards = [
                self._card_detail(card)
                for card in list(cards.values())[:10]
            ]
        summary = (
            f"Goal: {result.plan.goal.description if result.plan else 'unknown'}\n"
            f"Failure type: {result.failure_type}\n"
            f"Error: {result.error}\n"
            f"Cards: {list(cards)}\n"
            f"Edges: {edge_lines}\n\n"
            f"Planned cards:\n{chr(10).join(path_cards)}\n\n"
            f"Executed steps:\n{self._action_detail(result)}\n"
        )
        prompt = (
            f"{summary}\n"
            "Propose the smallest patch that fixes the behavior after this "
            "failure. Do not only reword Intent or Evidence: add or fix "
            "executable Steps (or pre/postconditions/inputs) that change what "
            "runs. Write one Step per physical action; if the fix needs two "
            "Back presses, add two Back steps. You may update cards, add "
            "cards/edges, split a card "
            "(delete it; replacements go in new_cards), or merge two cards "
            "(keep the first, delete the second). Return JSON."
        )
        try:
            data = self.llm.complete_json(prompt, _PATCH_SCHEMA)
        except LLMParseError as exc:
            logger.warning("failure patch parse failed: %s", exc)
            return GraphPatch(reason="failure patch parse error")

        patch = self._validate(data, cards)
        if patch is None:
            return GraphPatch(reason="invalid patch rejected")
        return patch

    def _validate(
        self,
        data: Any,
        cards: dict[str, FunctionCard],
    ) -> GraphPatch | None:
        if not isinstance(data, dict):
            return None
        existing = set(cards)

        raw_updates = data.get("card_updates") or []
        if not isinstance(raw_updates, list):
            return None
        card_updates: list[dict[str, Any]] = []
        for item in raw_updates:
            if not isinstance(item, dict):
                return None
            name = item.get("name")
            fields = item.get("fields", {})
            if (
                not isinstance(name, str)
                or name not in existing
                or not isinstance(fields, dict)
            ):
                return None
            card_updates.append({"name": name, "fields": fields})

        raw_new = data.get("new_cards") or []
        if not isinstance(raw_new, list):
            return None
        new_cards: list[FunctionCard] = []
        new_names: set[str] = set()
        for item in raw_new:
            if isinstance(item, FunctionCard):
                if item.name in existing or item.name in new_names:
                    return None
                new_cards.append(item)
                new_names.add(item.name)
                continue
            if not isinstance(item, dict):
                return None
            name = item.get("name")
            if (
                not isinstance(name, str)
                or not name
                or name in existing
                or name in new_names
            ):
                return None
            try:
                card = FunctionCard(
                    name=name,
                    intent=str(item.get("intent", "")),
                    inputs=_as_list(item.get("inputs")),
                    preconditions=str(item.get("preconditions", "")),
                    postconditions=str(item.get("postconditions", "")),
                    effects_outputs=str(
                        item.get(
                            "effects_outputs",
                            item.get("Effects/Outputs", ""),
                        )
                    ),
                    steps=_as_list(item.get("steps")),
                    evidence=_as_list(item.get("evidence")),
                    success_count=int(item.get("success_count", 0) or 0),
                    attempt_count=int(item.get("attempt_count", 0) or 0),
                )
            except (TypeError, ValueError):
                return None
            new_cards.append(card)
            new_names.add(name)

        all_names = existing | new_names

        raw_edges = data.get("edge_updates") or []
        if not isinstance(raw_edges, list):
            return None
        edge_updates: list[dict[str, Any]] = []
        for item in raw_edges:
            if not isinstance(item, dict):
                return None
            from_card = item.get("from")
            to_card = item.get("to")
            edge_type = item.get("type")
            action = str(item.get("action") or "add").lower()
            if (
                not isinstance(from_card, str)
                or not isinstance(to_card, str)
                or edge_type not in EDGE_PRIORITY
                or action not in {"add", "update", "remove"}
            ):
                return None
            if action != "remove" and (
                from_card not in all_names or to_card not in all_names
            ):
                return None
            edge_updates.append(dict(item, action=action))

        raw_split = data.get("split") or []
        if not isinstance(raw_split, list):
            return None
        split: list[dict[str, Any]] = []
        for item in raw_split:
            if not isinstance(item, dict):
                return None
            name = item.get("name") or item.get("card")
            if not isinstance(name, str) or name not in existing:
                return None
            split.append(dict(item))

        raw_merge = data.get("merge") or []
        if not isinstance(raw_merge, list):
            return None
        merge: list[dict[str, Any]] = []
        for item in raw_merge:
            if not isinstance(item, dict):
                return None
            keep = item.get("keep") or item.get("from") or item.get("first")
            drop = (
                item.get("delete")
                or item.get("to")
                or item.get("second")
            )
            if (
                not isinstance(keep, str)
                or not isinstance(drop, str)
                or keep not in existing
                or drop not in existing
            ):
                return None
            merge.append(dict(item))

        if not self._has_executable_change(
            card_updates, new_cards, edge_updates, split, merge
        ):
            return None

        return GraphPatch(
            new_cards=new_cards,
            card_updates=card_updates,
            edge_updates=edge_updates,
            split=split,
            merge=merge,
            reason=str(data.get("reason", "")),
        )

    @staticmethod
    def _has_executable_change(
        card_updates: list[dict[str, Any]],
        new_cards: list[FunctionCard],
        edge_updates: list[dict[str, Any]],
        split: list[dict[str, Any]],
        merge: list[dict[str, Any]],
    ) -> bool:
        if new_cards or edge_updates or split or merge:
            return True
        for update in card_updates:
            fields = update.get("fields") or {}
            normalized = {
                re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
                for key in fields
            }
            if normalized & _EXECUTABLE_FIELDS:
                return True
        return False

    def update(self, result: RunResult) -> GraphPatch:
        if result.success:
            return self._success_patch(result)
        return self._failure_patch(result)

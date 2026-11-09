"""Detect missing capabilities, probe them, and propose graph patches."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol

from specfcg.graph.store import GraphStore
from specfcg.llm.client import LLMClient, LLMParseError
from specfcg.maintainer.builder import EdgeBuilder
from specfcg.maintainer.miner import CardMiner
from specfcg.models import (
    Goal,
    GraphPatch,
    MissingCapability,
    Trace,
)

logger = logging.getLogger(__name__)

_GAP_SCHEMA = '{"gap": "missing capability or null", "blocked_precondition": "..."}'
_CAPABILITY_SCHEMA = (
    '{"capabilities": [{"name": "attach_photo", '
    '"intent": "attach a photo", "preconditions": "...", '
    '"postconditions": "...", "inputs": [], "probe": [], '
    '"confidence": 0.5}]}'
)


class ProbeRunner(Protocol):
    def run(
        self, capability: MissingCapability, state: str
    ) -> Trace | None: ...


class CapabilityCompleter:
    def __init__(
        self,
        llm: LLMClient,
        store: GraphStore,
        miner: CardMiner,
        builder: EdgeBuilder,
        probe: ProbeRunner,
        max_hypotheses: int = 5,
        max_probes: int = 3,
        max_rounds: int = 2,
    ) -> None:
        self.llm = llm
        self.store = store
        self.miner = miner
        self.builder = builder
        self.probe = probe
        self.max_hypotheses = max_hypotheses
        self.max_probes = max_probes
        self.max_rounds = max_rounds

    def _detect_gap(self, goal: Goal, state: str) -> str | None:
        cards = self.store.cards.all()
        card_lines = "\n".join(
            f"- {name}: {card.intent}; pre={card.preconditions!r}; "
            f"post={card.postconditions!r}"
            for name, card in cards.items()
        )
        prompt = (
            f"Goal: {goal.description}\nState:\n{state[:4000]}\n\n"
            f"Known cards:\n{card_lines}\n\n"
            "Is a capability missing that blocks this goal? "
            "Return the missing capability, or null if the graph is "
            "sufficient."
        )
        try:
            data = self.llm.complete_json(prompt, _GAP_SCHEMA)
        except LLMParseError as exc:
            logger.warning("gap detection failed: %s", exc)
            return None
        gap = data.get("gap") if isinstance(data, dict) else None
        if gap is None:
            return None
        text = str(gap).strip()
        return text or None

    def _hypothesize(
        self, gap: str, goal: Goal, max_hypotheses: int
    ) -> list[MissingCapability]:
        prompt = (
            f"Goal: {goal.description}\nMissing capability: {gap}\n\n"
            f"Propose up to {max_hypotheses} missing capabilities as "
            "concrete user-level functions with pre/postconditions and a "
            "short probe plan."
        )
        try:
            data = self.llm.complete_json(prompt, _CAPABILITY_SCHEMA)
        except LLMParseError as exc:
            logger.warning("capability hypothesis failed: %s", exc)
            return []
        raw = data.get("capabilities") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return []

        capabilities: list[MissingCapability] = []
        for item in raw[: max(0, max_hypotheses)]:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            raw_inputs = item.get("inputs") or []
            raw_probe = item.get("probe") or []
            confidence = item.get("confidence", 0.0)
            capabilities.append(
                MissingCapability(
                    name=name.strip(),
                    intent=str(item.get("intent", "")),
                    preconditions=str(item.get("preconditions", "")),
                    postconditions=str(item.get("postconditions", "")),
                    inputs=(
                        [str(value) for value in raw_inputs]
                        if isinstance(raw_inputs, list)
                        else []
                    ),
                    probe=(
                        [str(value) for value in raw_probe]
                        if isinstance(raw_probe, list)
                        else []
                    ),
                    confidence=(
                        float(confidence)
                        if isinstance(confidence, (int, float))
                        else 0.0
                    ),
                    evidence=str(item.get("evidence", "")),
                )
            )
        return capabilities

    def _record_negative(
        self,
        goal: Goal,
        capability: MissingCapability,
        reason: str,
    ) -> None:
        path: Path = self.store.root / "completion" / "negative.jsonl"
        record = {
            "goal": goal.description,
            "capability": capability.name,
            "reason": reason,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("could not record negative capability: %s", exc)

    def _patch_from_trace(
        self,
        capability: MissingCapability,
        trace: Trace,
    ) -> GraphPatch | None:
        if not trace.steps:
            return None
        episode = {
            "start": 0,
            "end": len(trace.steps) - 1,
            "name": capability.name,
            "intent": capability.intent or capability.name,
        }
        card = self.miner.draft(episode, trace)
        if not card.preconditions and capability.preconditions:
            card.preconditions = capability.preconditions
        if not card.postconditions and capability.postconditions:
            card.postconditions = capability.postconditions
        if not card.inputs and capability.inputs:
            card.inputs = list(capability.inputs)

        cards = self.store.cards.all()
        existing = cards.get(card.name)
        new_cards = []
        card_updates = []
        if existing is None:
            cards[card.name] = card
            new_cards = [card]
        else:
            evidence = list(existing.evidence)
            for item in card.evidence:
                if item not in evidence:
                    evidence.append(item)
            fields: dict[str, Any] = {
                "evidence": evidence,
                "success_count": existing.success_count
                + card.success_count,
                "attempt_count": existing.attempt_count
                + card.attempt_count,
            }
            for attr in (
                "intent",
                "inputs",
                "preconditions",
                "postconditions",
                "effects_outputs",
                "steps",
            ):
                if not getattr(existing, attr) and getattr(card, attr):
                    fields[attr] = getattr(card, attr)
            merged = replace(existing, **fields)
            cards[card.name] = merged
            card_updates = [{"name": card.name, "fields": fields}]

        segments = [
            {
                "trace_id": trace.trace_id,
                "start": index,
                "end": index,
                "card": card.name,
            }
            for index in range(len(trace.steps))
        ]
        edge_updates = [
            {
                "from": edge.from_card,
                "to": edge.to_card,
                "type": edge.type,
                "action": "add",
                "description": edge.description,
                "evidence": edge.evidence,
            }
            for edge in self.builder.build(cards, segments)
        ]
        return GraphPatch(
            new_cards=new_cards,
            card_updates=card_updates,
            edge_updates=edge_updates,
            reason=f"completed capability {capability.name}",
        )

    def complete(
        self, goal: Goal, state: str
    ) -> GraphPatch | None:
        hypotheses_used = 0
        probes_used = 0

        for _round in range(max(1, self.max_rounds)):
            gap = self._detect_gap(goal, state)
            if gap is None:
                return None
            hypotheses = self._hypothesize(
                gap, goal, self.max_hypotheses
            )
            if not hypotheses:
                return None

            for capability in hypotheses:
                if (
                    hypotheses_used >= self.max_hypotheses
                    or probes_used >= self.max_probes
                ):
                    return None
                hypotheses_used += 1
                probes_used += 1

                trace = self.probe.run(capability, state)
                if trace is None:
                    self._record_negative(
                        goal, capability, "probe returned no trace"
                    )
                    continue
                patch = self._patch_from_trace(capability, trace)
                if patch is not None:
                    return patch
                self._record_negative(
                    goal, capability, "probe trace was empty"
                )

            if (
                hypotheses_used >= self.max_hypotheses
                or probes_used >= self.max_probes
            ):
                return None

        return None

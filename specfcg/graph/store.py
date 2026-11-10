"""JSONL graph storage, patch application, and version backups."""

from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from specfcg.cards.store import CardStore
from specfcg.models import EDGE_PRIORITY, Edge, FunctionCard, Graph, GraphPatch

logger = logging.getLogger(__name__)

_FIELD_ALIASES = {
    "intent": "intent",
    "inputs": "inputs",
    "preconditions": "preconditions",
    "postconditions": "postconditions",
    "effects_outputs": "effects_outputs",
    "steps": "steps",
    "evidence": "evidence",
    "success_count": "success_count",
    "attempt_count": "attempt_count",
}

_FIELD_SPLIT_RE = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+")


def _normalize_field(key: str) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")
    return _FIELD_ALIASES.get(normalized)


def _split_values(value: str, *, numbered: bool) -> list[str]:
    if numbered:
        items = [
            _FIELD_SPLIT_RE.sub("", line).strip()
            for line in value.splitlines()
        ]
    else:
        items = [item.strip() for item in value.split(",")]
    return [item for item in items if item]


def _coerce(attr: str, value: Any) -> Any:
    if attr in {"inputs", "steps", "evidence"}:
        if isinstance(value, list):
            return [str(item) for item in value]
        return _split_values(str(value), numbered=attr == "steps")
    if attr in {"success_count", "attempt_count"}:
        return int(value)
    return str(value)


class GraphStore:
    """Persistent FCG: cards on disk plus `graph/edges.jsonl`."""

    def __init__(self, root: Path, cards: CardStore) -> None:
        self.root = Path(root)
        self.cards = cards
        self.graph_dir = self.root / "graph"
        self.edges_path = self.graph_dir / "edges.jsonl"
        self.journal_path = self.graph_dir / "journal.jsonl"

    def load(self) -> Graph:
        return Graph(cards=self.cards.all(), edges=self.edges())

    def journal(self) -> list[dict[str, Any]]:
        """Every graph mutation, in the order it was applied.

        The page animates graph construction, so each patch has to leave a
        replayable record: what it added, what it changed, and what the graph
        looked like afterwards. Without this the only trace of construction is
        a final snapshot, which cannot show *how* the graph grew.
        """
        if not self.journal_path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for line in self.journal_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("skipping malformed journal line: %s", exc)
                continue
            if isinstance(entry, dict):
                entries.append(entry)
        return entries

    def _append_journal(
        self, patch: GraphPatch, before_cards: set[str], before_edges: set[tuple[str, str, str]]
    ) -> None:
        graph = self.load()
        after_cards = set(graph.cards)
        after_edges = {
            (edge.from_card, edge.to_card, edge.type) for edge in graph.edges
        }
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "reason": patch.reason,
            "cards_added": len(after_cards - before_cards),
            "cards_removed": len(before_cards - after_cards),
            "cards_updated": len(patch.card_updates),
            "edges_added": len(after_edges - before_edges),
            "edges_removed": len(before_edges - after_edges),
            "cards_total": len(after_cards),
            "edges_total": len(after_edges),
            "new_cards": sorted(after_cards - before_cards),
            "new_edges": [
                {"from": edge.from_card, "to": edge.to_card, "type": edge.type}
                for edge in graph.edges
                if (edge.from_card, edge.to_card, edge.type) not in before_edges
            ],
            "edge_list": [
                {"from": edge.from_card, "to": edge.to_card, "type": edge.type}
                for edge in graph.edges
            ],
        }
        self.graph_dir.mkdir(parents=True, exist_ok=True)
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def edges(self) -> list[Edge]:
        if not self.edges_path.exists():
            return []
        edges: list[Edge] = []
        for line in self.edges_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("skipping malformed edge line: %s", exc)
                continue
            if not isinstance(data, dict):
                continue
            from_card = data.get("from")
            to_card = data.get("to")
            edge_type = data.get("type")
            if not from_card or not to_card or edge_type not in EDGE_PRIORITY:
                continue
            raw_evidence = data.get("evidence") or []
            if not isinstance(raw_evidence, list):
                raw_evidence = [raw_evidence]
            edges.append(
                Edge(
                    from_card=str(from_card),
                    to_card=str(to_card),
                    type=edge_type,
                    description=str(data.get("description", "")),
                    evidence=[str(item) for item in raw_evidence],
                )
            )
        return edges

    def _save_edges(self, edges: list[Edge]) -> None:
        self.graph_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(
                {
                    "from": edge.from_card,
                    "to": edge.to_card,
                    "type": edge.type,
                    "description": edge.description,
                    "evidence": edge.evidence,
                },
                ensure_ascii=False,
            )
            for edge in edges
        ]
        text = "\n".join(lines)
        if text:
            text += "\n"
        self.edges_path.write_text(text, encoding="utf-8")

    def _apply_card_update(self, update: dict[str, Any]) -> None:
        name = update.get("name")
        if not name:
            return
        try:
            card = self.cards.load(str(name))
        except FileNotFoundError:
            logger.warning("card update skipped for unknown card %s", name)
            return
        fields = update.get("fields") or {}
        if not isinstance(fields, dict):
            return
        for key, value in fields.items():
            attr = _normalize_field(str(key))
            if attr is None:
                continue
            try:
                coerced = _coerce(attr, value)
            except (TypeError, ValueError) as exc:
                logger.warning(
                    "card update field skipped %s=%r: %s",
                    key,
                    value,
                    exc,
                )
                continue
            setattr(card, attr, coerced)
        self.cards.save(card)

    def _apply_edge_updates(
        self,
        edges: list[Edge],
        updates: list[dict[str, Any]],
        names: set[str],
    ) -> list[Edge]:
        for update in updates:
            if not isinstance(update, dict):
                continue
            from_card = update.get("from")
            to_card = update.get("to")
            edge_type = update.get("type")
            action = str(update.get("action") or "add").lower()
            if (
                not from_card
                or not to_card
                or edge_type not in EDGE_PRIORITY
            ):
                continue
            key = (str(from_card), str(to_card), edge_type)
            if action == "remove":
                edges = [
                    edge
                    for edge in edges
                    if (edge.from_card, edge.to_card, edge.type) != key
                ]
                continue
            if from_card not in names or to_card not in names:
                logger.warning("edge skipped for unknown endpoint: %s", key)
                continue

            existing = next(
                (
                    edge
                    for edge in edges
                    if (edge.from_card, edge.to_card, edge.type) == key
                ),
                None,
            )
            raw_evidence = update.get("evidence") or []
            if not isinstance(raw_evidence, list):
                raw_evidence = [raw_evidence]
            evidence = [str(item) for item in raw_evidence]

            if existing is not None:
                description = update.get("description")
                if description:
                    existing.description = str(description)
                for item in evidence:
                    if item not in existing.evidence:
                        existing.evidence.append(item)
                continue

            edges.append(
                Edge(
                    from_card=key[0],
                    to_card=key[1],
                    type=edge_type,
                    description=str(update.get("description", "")),
                    evidence=evidence,
                )
            )
        return edges

    def apply_patch(self, patch: GraphPatch) -> None:
        before_cards = set(self.cards.all())
        before_edges = {
            (edge.from_card, edge.to_card, edge.type) for edge in self.edges()
        }
        for card in patch.new_cards:
            self.cards.save(card)
        for update in patch.card_updates:
            self._apply_card_update(update)

        edges = self.edges()
        names = set(self.cards.all())
        edges = self._apply_edge_updates(edges, patch.edge_updates, names)

        for item in patch.split:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("card")
            if not name:
                continue
            self.cards.delete(str(name))
            edges = [
                edge
                for edge in edges
                if edge.from_card != name and edge.to_card != name
            ]

        for item in patch.merge:
            if not isinstance(item, dict):
                continue
            keep = item.get("keep") or item.get("from") or item.get("first")
            drop = (
                item.get("delete")
                or item.get("to")
                or item.get("second")
            )
            if not keep or not drop or keep == drop:
                continue
            try:
                keep_card = self.cards.load(str(keep))
                drop_card = self.cards.load(str(drop))
            except FileNotFoundError:
                logger.warning("merge skipped for missing cards: %s", item)
                continue
            self._merge_cards(keep_card, drop_card)
            self.cards.save(keep_card)
            self.cards.delete(str(drop))
            edges = self._rewrite_merged_edges(edges, str(keep), str(drop))

        self._save_edges(edges)
        self._append_journal(patch, before_cards, before_edges)

    @staticmethod
    def _merge_cards(keep: FunctionCard, drop: FunctionCard) -> None:
        for item in drop.evidence:
            if item not in keep.evidence:
                keep.evidence.append(item)
        keep.success_count += drop.success_count
        keep.attempt_count += drop.attempt_count

    @staticmethod
    def _rewrite_merged_edges(
        edges: list[Edge], keep: str, drop: str
    ) -> list[Edge]:
        rewritten: list[Edge] = []
        index: dict[tuple[str, str, str], Edge] = {}
        for edge in edges:
            from_card = keep if edge.from_card == drop else edge.from_card
            to_card = keep if edge.to_card == drop else edge.to_card
            key = (from_card, to_card, edge.type)
            if key in index:
                existing = index[key]
                for item in edge.evidence:
                    if item not in existing.evidence:
                        existing.evidence.append(item)
                continue
            merged = Edge(
                from_card=from_card,
                to_card=to_card,
                type=edge.type,
                description=edge.description,
                evidence=list(edge.evidence),
            )
            index[key] = merged
            rewritten.append(merged)
        return rewritten

    def backup(self) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        version = self.graph_dir / "versions" / stamp
        version.mkdir(parents=True, exist_ok=False)
        if self.cards.cards_dir.exists():
            shutil.copytree(self.cards.cards_dir, version / "cards")
        else:
            (version / "cards").mkdir()
        if self.edges_path.exists():
            shutil.copy2(self.edges_path, version / "edges.jsonl")
        return version

    def restore(self, version: Path) -> None:
        version = Path(version)
        if not version.exists():
            raise FileNotFoundError(version)

        if self.cards.cards_dir.exists():
            shutil.rmtree(self.cards.cards_dir)
        backup_cards = version / "cards"
        if backup_cards.exists():
            shutil.copytree(backup_cards, self.cards.cards_dir)
        else:
            self.cards.cards_dir.mkdir(parents=True, exist_ok=True)

        if self.edges_path.exists():
            self.edges_path.unlink()
        backup_edges = version / "edges.jsonl"
        if backup_edges.exists():
            self.graph_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_edges, self.edges_path)

    def neighbors(self, name: str, type: str | None = None) -> list[Edge]:
        matches = [
            edge
            for edge in self.edges()
            if edge.from_card == name and (type is None or edge.type == type)
        ]
        return sorted(
            matches, key=lambda edge: EDGE_PRIORITY.index(edge.type)
        )

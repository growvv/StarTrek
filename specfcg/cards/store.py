"""Filesystem storage for function cards."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from specfcg.cards.parser import CardParseError, parse_card, render_card
from specfcg.models import FunctionCard

logger = logging.getLogger(__name__)


def card_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "card"


class CardStore:
    """One Markdown file per function card under `<root>/cards/`."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.cards_dir = self.root / "cards"

    def _path(self, name: str) -> Path:
        return self.cards_dir / f"{card_slug(name)}.md"

    def save(self, card: FunctionCard) -> None:
        self.cards_dir.mkdir(parents=True, exist_ok=True)
        self._path(card.name).write_text(render_card(card), encoding="utf-8")

    def load(self, name: str) -> FunctionCard:
        path = self._path(name)
        if not path.exists():
            raise FileNotFoundError(path)
        return parse_card(path.read_text(encoding="utf-8"))

    def all(self) -> dict[str, FunctionCard]:
        cards: dict[str, FunctionCard] = {}
        if not self.cards_dir.exists():
            return cards
        for path in sorted(self.cards_dir.glob("*.md")):
            try:
                card = parse_card(path.read_text(encoding="utf-8"))
            except (CardParseError, OSError) as exc:
                logger.warning("skipping malformed card %s: %s", path, exc)
                continue
            cards[card.name] = card
        return cards

    def delete(self, name: str) -> None:
        path = self._path(name)
        if path.exists():
            path.unlink()

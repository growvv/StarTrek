#!/usr/bin/env python3
"""Remove the retired Steps section from the cards under one or more graphs.

    python scripts/migrate_cards.py runs/mobileworld/*/graph

Each argument is a graph root; every ``cards/*.md`` below it is migrated in
place.  The migration only deletes the Steps section (see
``specfcg.cards.migrate``), so running it twice changes nothing the second
time.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from specfcg.cards.migrate import migrate  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="+", type=Path)
    args = parser.parse_args(argv)

    total = 0
    for root in args.roots:
        cards_dir = root / "cards"
        if not cards_dir.is_dir():
            print(f"{root}: no cards/ directory", file=sys.stderr)
            continue
        changed = 0
        for path in sorted(cards_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            migrated = migrate(text)
            if migrated != text:
                path.write_text(migrated, encoding="utf-8", newline="")
                changed += 1
        print(f"{root}: {changed} card(s) migrated")
        total += changed
    print(f"total: {total} card(s) migrated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

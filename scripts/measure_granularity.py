#!/usr/bin/env python3
"""How many distinct behaviours does a graph's cards describe?

Every card is meant to be one node with its own meaning.  Two cards that send
the device the same actions on the same controls are one behaviour described
twice: the search pays for both and the graph reports a richer inventory than
the app has.

The measurement is deterministic -- it reuses the compiler's own step parse,
so it compares what the cards would actually do, not what they are called.
There is no similarity threshold: a surface is equal or it is not.

It is a measure of behavioural redundancy, not a verdict on correctness.  The
same tap can be a different function in a different state: activitydiary's
start/stop/switch/details cards all tap the activity card and differ only in
their preconditions.  A group sharing one surface is therefore something to
inspect, not something to merge.

Run:
  PYTHONPATH=. python scripts/measure_granularity.py
  PYTHONPATH=. python scripts/measure_granularity.py --app omninotes
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from specfcg.benchmark.granularity import granularity  # noqa: E402
from specfcg.cards.store import CardStore  # noqa: E402

APPS = ("activitydiary", "amaze", "markor", "omninotes")


def measure(app: str, runs: Path) -> dict | None:
    """The granularity record for one app, or None when it has no graph."""
    root = runs / app / "graph"
    if not root.exists():
        return None
    cards = CardStore(root).all()
    if not cards:
        return None
    return granularity(cards).as_record()


def report(apps: tuple[str, ...], runs: Path) -> dict[str, dict]:
    records = {}
    for app in apps:
        record = measure(app, runs)
        if record is None:
            print(f"{app}: no graph", file=sys.stderr)
            continue
        records[app] = record
        score = record["score"]
        shown = "—" if score is None else f"{score:.3f}"
        print(
            f"{app:14s} cards={record['cards']:3d} "
            f"measured={record['measured']:3d} "
            f"distinct={record['distinct']:3d} score={shown}",
            flush=True,
        )
        for group in record["duplicate_groups"]:
            print(f"      same actions: {', '.join(group)}", flush=True)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="measure-granularity")
    parser.add_argument("--app", action="append", default=[])
    parser.add_argument("--runs", default="runs/mobileworld")
    parser.add_argument(
        "--out", default="runs/mobileworld/granularity.json"
    )
    args = parser.parse_args(argv)
    apps = tuple(args.app) or APPS
    records = report(apps, ROOT / args.runs)
    if not records:
        print("no graph to measure", file=sys.stderr)
        return 2
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"out": str(out), "apps": sorted(records)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

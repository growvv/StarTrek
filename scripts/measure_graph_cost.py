#!/usr/bin/env python3
"""What each graph spent inferring semantic edges.

Read from the construction journal, so the number is the graph's own record
rather than a stopwatch around a run.  A builder that re-derives the edges
after every mined trace records one call per trace; deriving them once over
the complete card set records one call, and this is how the difference shows
up in the artifacts.

Run:
  PYTHONPATH=. python scripts/measure_graph_cost.py
  PYTHONPATH=. python scripts/measure_graph_cost.py --root runs/ab-batch/activitydiary/graph
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from specfcg.benchmark.graph_cost import semantic_cost  # noqa: E402

APPS = ("activitydiary", "amaze", "markor", "omninotes")


def journal(root: Path) -> Path | None:
    """The construction journal under a graph root, in either layout.

    A graph written by ``build_app_graph --out X`` lives at ``X/graph/``;
    one recorded under ``runs/mobileworld/<app>/graph`` keeps its store in a
    nested ``graph/`` directory.
    """
    for candidate in (root / "graph" / "journal.jsonl", root / "journal.jsonl"):
        if candidate.exists():
            return candidate
    return None


def cost(root: Path) -> dict | None:
    path = journal(root)
    if path is None:
        return None
    frames = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return semantic_cost(frames)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="measure-graph-cost")
    parser.add_argument("--app", action="append", default=[])
    parser.add_argument("--runs", default="runs/mobileworld")
    parser.add_argument("--root", default="", help="one explicit graph root")
    parser.add_argument("--out", default="runs/mobileworld/graph-cost.json")
    args = parser.parse_args(argv)

    if args.root:
        record = cost(ROOT / args.root)
        if record is None:
            print("no journal under that root", file=sys.stderr)
            return 2
        print(f"{args.root}: {record['calls']} calls, {record['seconds'] / 60:.1f} min")
        print(json.dumps(record))
        return 0

    records: dict[str, dict] = {}
    for app in tuple(args.app) or APPS:
        record = cost(ROOT / args.runs / app / "graph")
        if record is None:
            print(f"{app}: no journal", file=sys.stderr)
            continue
        records[app] = record
        print(
            f"{app:14s} semantic calls={record['calls']:3d} "
            f"time={record['seconds'] / 60:6.1f} min",
            flush=True,
        )
    if not records:
        return 2
    out = ROOT / args.out
    out.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"out": str(out), "apps": sorted(records)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

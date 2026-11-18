#!/usr/bin/env python3
"""Print the same-function groups the builder recorded for each app.

This is a diagnosis, not a score.  With the action lists gone there is no
deterministic oracle for "same function", so the groups are a model judgement
over the contracts; they are reported for a person to inspect and are never
merged automatically.

    python scripts/measure_duplicates.py
    python scripts/measure_duplicates.py runs/mobileworld
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def same_function_path(app_dir: Path) -> Path | None:
    """The groups file under an app directory, in either layout.

    A graph written by ``build_app_graph --out X`` keeps its store in
    ``X/graph/``; one recorded under ``runs/mobileworld/<app>/graph`` nests a
    second ``graph/``.  Both are the same graph, so both are read — the same
    rule ``measure_graph_cost.py`` applies to the journal.
    """
    for candidate in (
        app_dir / "graph" / "graph" / "same_function.json",
        app_dir / "graph" / "same_function.json",
        app_dir / "same_function.json",
    ):
        if candidate.exists():
            return candidate
    return None


def groups_for(app_dir: Path) -> list[list[str]]:
    path = same_function_path(app_dir)
    if path is None:
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [
        [str(name) for name in group]
        for group in (raw.get("groups") or [])
        if isinstance(group, list) and len(group) >= 2
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="?", default=str(ROOT / "runs" / "mobileworld"))
    args = parser.parse_args(argv)

    runs = Path(args.runs)
    if not runs.is_dir():
        print(f"no runs directory at {runs}", file=sys.stderr)
        return 1

    total = 0
    for app_dir in sorted(p for p in runs.iterdir() if p.is_dir()):
        groups = groups_for(app_dir)
        print(f"{app_dir.name}: {len(groups)} group(s)")
        for group in groups:
            print("  " + " / ".join(group))
        total += len(groups)
    print(f"\n{total} group(s) total")
    print(
        "These are model judgements over the card contracts, not a measured "
        "score.  They are reported, never merged automatically."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

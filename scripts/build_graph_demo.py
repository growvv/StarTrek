#!/usr/bin/env python3
"""Grow the FCG one trace at a time, recording every patch.

This is the demo build: start from an empty graph, feed it real OmniNotes
traces in the order an explorer would collect them, and let the pipeline do
what it normally does — segment, mine a card, add sequence edges from the
observed order, then infer semantic edges over the cards present so far.
Each `apply_patch` appends a journal entry, so the resulting
`graph/journal.jsonl` is the complete construction history the site animates.

Run:
  PYTHONIOENCODING=utf-8 python scripts/build_graph_demo.py \
      --root runs/real/demo_graph --traces omninotes-create-note-2,...
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from specfcg.cli import build_pipeline  # noqa: E402
from specfcg.config import load_config  # noqa: E402
from specfcg.traces.recorder import trace_from_dict  # noqa: E402

DEFAULT_TRACES = [
    "omninotes-create-note-2",
    "omninotes-search-1",
    "omninotes-open-note-1",
    "omninotes-share-1",
    "omninotes-archive-1",
    "omninotes-sort-1",
    "omninotes-pin-1",
    "omninotes-checklist-1",
    "omninotes-delete-1",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build-graph-demo")
    parser.add_argument("--config", default=str(ROOT / "config" / "llm.yaml"))
    parser.add_argument("--root", default=str(ROOT / "runs" / "real" / "demo_graph"))
    parser.add_argument("--traces", default=",".join(DEFAULT_TRACES))
    parser.add_argument(
        "--trace-dir", default=str(ROOT / "runs" / "real")
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    if root.exists():
        import shutil

        shutil.rmtree(root)
    root.mkdir(parents=True)

    config = load_config(Path(args.config))
    config.paths.root = str(root)
    pipeline = build_pipeline(config, fake_llm=False, fake_device=False)

    trace_dir = Path(args.trace_dir)
    for name in [item.strip() for item in args.traces.split(",") if item.strip()]:
        path = trace_dir / f"{name}.json"
        if not path.exists():
            print(f"missing trace: {path}", file=sys.stderr)
            return 1
        trace = trace_from_dict(json.loads(path.read_text(encoding="utf-8")))
        print(f"--- mining {name} ---", flush=True)
        patch = pipeline.mine_trace(trace)
        print(
            f"  new cards: {[card.name for card in patch.new_cards]}",
            flush=True,
        )
        edges = pipeline.build_graph([])
        print(f"  semantic edges now: {len(edges)}", flush=True)
        print(
            f"  graph: {len(pipeline.graph.cards)} cards, "
            f"{len(pipeline.graph.edges)} edges",
            flush=True,
        )

    journal = pipeline.store.journal()
    print(f"journal entries: {len(journal)}")
    print(f"root: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

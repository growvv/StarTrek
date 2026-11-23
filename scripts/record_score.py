#!/usr/bin/env python3
"""Record the current measured state as one point on the score curve.

Every iteration of the self-optimization loop ends here: the experiment
records under ``runs/mobileworld`` are scored, the point is appended to
``score-history.json``, and the report draws the curve from that file.  The
score is never typed in -- it is a function of the records on disk.

Usage:
  python scripts/record_score.py --label baseline
  python scripts/record_score.py --label planner-verification
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from specfcg.scoring.scorecard import (  # noqa: E402
    DIMENSIONS,
    collect_entries,
    record_point,
    scorecard,
)

_RECORD_KEYS = ("coverage", "random", "probes", "selfopt", "bench")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="record-score")
    parser.add_argument("--runs", default="runs/mobileworld")
    parser.add_argument(
        "--history", default="runs/mobileworld/score-history.json"
    )
    parser.add_argument("--label", required=True)
    args = parser.parse_args(argv)

    entries = [
        entry
        for entry in collect_entries(ROOT / args.runs)
        if any(entry.get(key) for key in _RECORD_KEYS)
    ]
    if not entries:
        print(
            f"no scored records under {args.runs}", file=sys.stderr
        )
        return 2

    card = scorecard(entries)
    point = record_point(ROOT / args.history, args.label, card)
    print(
        json.dumps(
            {
                "iteration": point["iteration"],
                "label": point["label"],
                "综合": point["overall"],
                "dims": point["dims"],
                "per_app": point["per_app"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(
        "综合 "
        + "，".join(
            f"{label} {point['dims'][key]:.0f}"
            for key, label, _source in DIMENSIONS
        )
        + f" → {point['overall']:.0f}/100",
        file=sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

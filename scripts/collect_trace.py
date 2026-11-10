#!/usr/bin/env python3
"""Collect a scripted real-device trace in SpecFCG JSON format.

Example actions file:
[
  {"action": "click", "target": "resourceId=app:id/fab", "wait": 1.2},
  {"action": "input", "target": "resourceId=app:id/title", "args": "Trip"},
  {"action": "back", "wait": 1.0}
]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from specfcg.executor.device import Uiautomator2Device
from specfcg.traces.recorder import trace_to_dict
from specfcg.traces.scripted import run_actions


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_") or "trace"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="collect-trace")
    parser.add_argument("--serial", default=None)
    parser.add_argument("--app", required=True, help="Android package name")
    parser.add_argument("--actions", required=True, type=Path)
    parser.add_argument("--trace-id", required=True)
    parser.add_argument("--goal", default="")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--no-start",
        action="store_true",
        help="record the current screen without launching the app",
    )
    args = parser.parse_args(argv)

    actions = json.loads(args.actions.read_text(encoding="utf-8"))
    if not isinstance(actions, list):
        raise SystemExit("actions JSON must be a list")

    device = Uiautomator2Device(args.serial)
    device.set_app(args.app)
    if not args.no_start:
        device.start_app(args.app)

    trace = run_actions(
        device,
        actions,
        app=args.app,
        trace_id=args.trace_id,
        goal=args.goal,
        metadata={
            "source": "scripted",
            "device": args.serial or "default",
            "actions_file": str(args.actions),
        },
    )

    out = args.out or Path("traces") / f"{_slug(args.trace_id)}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(trace_to_dict(trace), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    successes = sum(1 for step in trace.steps if step.success)
    print(
        f"trace={trace.trace_id} app={trace.app} "
        f"steps={len(trace.steps)} ok={successes} out={out}"
    )
    return 0 if successes == len(trace.steps) else 1


if __name__ == "__main__":
    raise SystemExit(main())

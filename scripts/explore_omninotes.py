#!/usr/bin/env python3
"""Record one exploratory trace on the real device.

Each exploration needs a defined starting state (a fresh notes list, or a
notes list with one note on it), so this script resets the app, runs the
untraced prep actions, and only then starts recording. What lands on disk is
a trace of the target function alone, which is what the card miner should see.

Run:
  PYTHONIOENCODING=utf-8 python scripts/explore_omninotes.py \
      --spec examples/explore/sort_by_title.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uiautomator2 as u2  # noqa: E402

from specfcg.executor.device import Uiautomator2Device  # noqa: E402
from specfcg.traces.recorder import trace_to_dict  # noqa: E402
from specfcg.traces.scripted import run_actions  # noqa: E402

PACKAGE = "it.feio.android.omninotes.foss"


def _prep_note(device: Any, title: str, content: str) -> None:
    device(resourceId=f"{PACKAGE}:id/fab_expand_menu_button").click()
    time.sleep(1.0)
    device(resourceId=f"{PACKAGE}:id/fab_note").click()
    time.sleep(1.2)
    device(resourceId=f"{PACKAGE}:id/detail_title").set_text(title)
    time.sleep(0.4)
    device(resourceId=f"{PACKAGE}:id/detail_content").set_text(content)
    time.sleep(0.4)
    device.press("back")
    time.sleep(0.8)
    device.press("back")
    time.sleep(1.5)


PREP = {
    "none": lambda device: None,
    "one_note": lambda device: _prep_note(device, "Groceries", "Buy milk"),
    "two_notes": lambda device: (
        _prep_note(device, "Groceries", "Buy milk"),
        _prep_note(device, "Work", "Finish report"),
    ),
}


def reset(serial: str) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "reset_omninotes.py"),
            "--serial",
            serial,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise SystemExit(
            "reset failed: "
            f"{completed.stdout.strip()} {completed.stderr.strip()}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="explore-omninotes")
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--serial", default="47261FDAS00DTQ")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "runs" / "real")
    args = parser.parse_args(argv)

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    trace_id = spec["trace_id"]
    prep = spec.get("prep", "none")
    if prep not in PREP:
        raise SystemExit(f"unknown prep {prep!r}; choose from {sorted(PREP)}")

    reset(args.serial)
    device = u2.connect(args.serial)
    PREP[prep](device)
    time.sleep(1.0)

    wrapper = Uiautomator2Device(args.serial)
    wrapper.set_app(PACKAGE)
    trace = run_actions(
        wrapper,
        spec["actions"],
        app=PACKAGE,
        trace_id=trace_id,
        goal=spec.get("goal", ""),
        metadata={"source": "exploration", "device": args.serial, "prep": prep},
    )
    out = args.out_dir / f"{trace_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(trace_to_dict(trace), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    ok = sum(1 for step in trace.steps if step.success)
    print(f"trace={trace_id} steps={len(trace.steps)} ok={ok} out={out}")
    return 0 if ok == len(trace.steps) else 1


if __name__ == "__main__":
    raise SystemExit(main())
